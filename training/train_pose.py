import torch
import torch.nn as nn
import torch.backends.cudnn as cudnn
import torch.optim
import os
import sys
import argparse
import time
sys.path.append('..')
import CocoFolder
import Mytransforms 
from utils import adjust_learning_rate as adjust_learning_rate
from utils import AverageMeter as AverageMeter
from utils import save_checkpoint as save_checkpoint
from utils import Config as Config
import pose_estimation
import pdb
import matplotlib.pyplot as plt

def parse():
    # python train_pose.py --gpu 0 1 
    # --train_dir /home/code/panhongyu/datasets/coco/filelist/train2017.txt /home/code/panhongyu/datasets/coco/masklist/train2017.txt /home/code/panhongyu/datasets/coco/json/train2017.json 
    # --val_dir /home/code/panhongyu/datasets/coco/filelist/val2017.txt /home/code/panhongyu/datasets/coco/masklist/val2017.txt /home/code/panhongyu/datasets/coco/json/val2017.json 
    # --config config.yml > $LOG
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str,
                        dest='config', help='to set the parameters')
    parser.add_argument('--gpu', default=[0], nargs='+', type=int,
                        dest='gpu', help='the gpu used')
    parser.add_argument('--pretrained', default=None,type=str,
                        dest='pretrained', help='the path of pretrained model')
    parser.add_argument('--root', default=None, type=str,
                        dest='root', help='the root of images')
    parser.add_argument('--train_dir', nargs='+', type=str,
                        dest='train_dir', help='the path of train file')
    parser.add_argument('--val_dir', default=None, nargs='+', type=str,
                        dest='val_dir', help='the path of val file')
    parser.add_argument('--num_classes', default=1000, type=int,
                        dest='num_classes', help='num_classes (default: 1000)')

    return parser.parse_args()

def construct_model(args):

    model = pose_estimation.PoseModel(num_point=19, num_vector=19, pretrained=False)
    # state_dict = torch.load(args.pretrained)['state_dict']
    # from collections import OrderedDict
    # new_state_dict = OrderedDict()
    # for k, v in state_dict.items():
    #     if 'fc' not in k:
    #         name = k[7:]
    #         new_state_dict[name] = v
    # model.load_state_dict(new_state_dict)
    # # model.fc = nn.Linear(2048, 80)
    model = torch.nn.DataParallel(model, device_ids=args.gpu).cuda()

    return model

def get_parameters(model, config, isdefault=True):

    if isdefault:
        return model.parameters(), [1.]
    lr_1 = []
    lr_2 = []
    lr_4 = []
    lr_8 = []
    params_dict = dict(model.module.named_parameters())
    for key, value in params_dict.items():
        if ('model1_' not in key) and ('model0.' not in key):
            if key[-4:] == 'bias':
                lr_8.append(value)
            else:
                lr_4.append(value)
        elif key[-4:] == 'bias':
            lr_2.append(value)
        else:
            lr_1.append(value)
    params = [{'params': lr_1, 'lr': config.base_lr},
            {'params': lr_2, 'lr': config.base_lr * 2.},
            {'params': lr_4, 'lr': config.base_lr * 4.},
            {'params': lr_8, 'lr': config.base_lr * 8.}]

    return params, [1., 2., 4., 8.]

def label2onhot(b_parsing_tensor):
    size = b_parsing_tensor.size()
    oneHot_size = (size[0], 20, size[2], size[3])
    b_parsing_label = torch.cuda.FloatTensor(torch.Size(oneHot_size)).zero_()
    b_parsing_label = b_parsing_label.scatter_(1, b_parsing_tensor.data.long().cuda(), 1.0)

    return b_parsing_label

def train_val(model, args):

    traindir = args.train_dir
    valdir = args.val_dir

    config = Config(args.config)
    cudnn.benchmark = True
    
    train_loader = torch.utils.data.DataLoader(
            CocoFolder.CocoFolder(traindir, 8,
                Mytransforms.Compose([Mytransforms.RandomResized(),
                Mytransforms.RandomRotate(40),
                Mytransforms.RandomCrop(368),
                Mytransforms.RandomHorizontalFlip(),
            ])),
            batch_size=config.batch_size, shuffle=True,
            num_workers=config.workers, pin_memory=True)

    if config.test_interval != 0 and args.val_dir is not None:
        val_loader = torch.utils.data.DataLoader(
                CocoFolder.CocoFolder(valdir, 2,
                    Mytransforms.Compose([Mytransforms.TestResized(368),
                ])),
                batch_size=config.batch_size, shuffle=False,
                num_workers=config.workers, pin_memory=True)
    
    criterion = nn.MSELoss().cuda()

    params, multiple = get_parameters(model, config, False)
    
    optimizer = torch.optim.SGD(params, config.base_lr, momentum=config.momentum,
                                weight_decay=config.weight_decay)
    
    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    losses_list = [AverageMeter() for i in range(12)]
    top1 = AverageMeter()
    topk = AverageMeter()
    
    end = time.time()
    iters = config.start_iters
    best_model = config.best_model
    learning_rate = config.base_lr

    model.train()

    heat_weight = 46 * 46 * 19 / 2.0 # for convenient to compare with origin code
    vec_weight = 46 * 46 * 38 / 2.0
    # pdb.set_trace()
    while iters < config.max_iter:
        for i, (input, heatmap, vecmap, mask) in enumerate(train_loader):
            
            input = label2onhot(input)*256
            # # normalize
            # 0 256
            # -0.5 0.5
            input = (input - 128) / 256

            learning_rate = adjust_learning_rate(optimizer, iters, config.base_lr, policy=config.lr_policy, policy_parameter=config.policy_parameter, multiple=multiple)
            data_time.update(time.time() - end)

            heatmap = heatmap.cuda()
            vecmap = vecmap.cuda()
            mask = mask.cuda()
            input_var = torch.autograd.Variable(input)
            heatmap_var = torch.autograd.Variable(heatmap)
            vecmap_var = torch.autograd.Variable(vecmap)
            mask_var = torch.autograd.Variable(mask)

            # vec1, heat1 = model(input_var, mask_var)
            vec1, heat1, vec2, heat2, vec3, heat3, vec4, heat4, vec5, heat5, vec6, heat6 = model(input_var, mask_var)
            loss1_1 = criterion(vec1, vecmap_var) * vec_weight
            loss1_2 = criterion(heat1, heatmap_var) * heat_weight
            loss2_1 = criterion(vec2, vecmap_var) * vec_weight
            loss2_2 = criterion(heat2, heatmap_var) * heat_weight
            loss3_1 = criterion(vec3, vecmap_var) * vec_weight
            loss3_2 = criterion(heat3, heatmap_var) * heat_weight
            loss4_1 = criterion(vec4, vecmap_var) * vec_weight
            loss4_2 = criterion(heat4, heatmap_var) * heat_weight
            loss5_1 = criterion(vec5, vecmap_var) * vec_weight
            loss5_2 = criterion(heat5, heatmap_var) * heat_weight
            loss6_1 = criterion(vec6, vecmap_var) * vec_weight
            loss6_2 = criterion(heat6, heatmap_var) * heat_weight
            
            loss = loss1_1 + loss1_2 + loss2_1 + loss2_2 + loss3_1 + loss3_2 + loss4_1 + loss4_2 + loss5_1 + loss5_2 + loss6_1 + loss6_2

            losses.update(loss.item(), input.size(0))
            for cnt, l in enumerate([loss1_1, loss1_2, loss2_1, loss2_2, loss3_1, loss3_2, loss4_1, loss4_2, loss5_1, loss5_2, loss6_1, loss6_2]):
                losses_list[cnt].update(l.item(), input.size(0))

            optimizer.zero_grad()
            loss.backward()

            optimizer.step()
        
            batch_time.update(time.time() - end)
            end = time.time()
    
            iters += 1
            if iters % config.display == 0:
                print('Train Iteration: {0}\t'
                    'Time {batch_time.sum:.3f}s / {1}iters, ({batch_time.avg:.3f})\t'
                    'Data load {data_time.sum:.3f}s / {1}iters, ({data_time.avg:3f})\n'
                    'Learning rate = {2}\n'
                    'Loss = {loss.val:.8f} (ave = {loss.avg:.8f})\n'.format(
                    iters, config.display, learning_rate, batch_time=batch_time,
                    data_time=data_time, loss=losses))
                for cnt in range(0,12,2):
                    print('Loss{0}_1 = {loss1.val:.8f} (ave = {loss1.avg:.8f})\t'
                        'Loss{1}_2 = {loss2.val:.8f} (ave = {loss2.avg:.8f})'.format(cnt / 2 + 1, cnt / 2 + 1, loss1=losses_list[cnt], loss2=losses_list[cnt + 1]))
                print (time.strftime('%Y-%m-%d %H:%M:%S -----------------------------------------------------------------------------------------------------------------\n', time.localtime()))

                batch_time.reset()
                data_time.reset()
                losses.reset()
                for cnt in range(12):
                    losses_list[cnt].reset()

            if iters % 10000 == 0:
                is_best = False

                save_checkpoint({
                    'iter': iters,
                    'state_dict': model.state_dict(),
                    }, iters, 'openpose_coco')

            # if iters % 1 == 0:
            #     print(heat1.cpu().data.numpy()[0,1])
            #     plt.imshow(heatmap_var.cpu().data.numpy()[0,1])
            #     plt.show()
            #     plt.imshow(heat1.cpu().data.numpy()[0,1])
            #     plt.show()
                
            if config.test_interval != 0 and args.val_dir is not None and iters % config.test_interval == 0:

                model.eval()
                for j, (input, heatmap, vecmap, mask) in enumerate(val_loader):
                    
                    input = label2onhot(input)*256
                    # # normalize
                    input = (input - 128) / 256
                    heatmap = heatmap.cuda()
                    vecmap = vecmap.cuda()
                    mask = mask.cuda()
                    input_var = torch.autograd.Variable(input, volatile=True)
                    heatmap_var = torch.autograd.Variable(heatmap, volatile=True)
                    vecmap_var = torch.autograd.Variable(vecmap, volatile=True)
                    mask_var = torch.autograd.Variable(mask, volatile=True)

                    vec1, heat1, vec2, heat2, vec3, heat3, vec4, heat4, vec5, heat5, vec6, heat6 = model(input_var, mask_var)

                    loss1_1 = criterion(vec1, vecmap_var) * vec_weight
                    loss1_2 = criterion(heat1, heatmap_var) * heat_weight
                    loss2_1 = criterion(vec2, vecmap_var) * vec_weight
                    loss2_2 = criterion(heat2, heatmap_var) * heat_weight
                    loss3_1 = criterion(vec3, vecmap_var) * vec_weight
                    loss3_2 = criterion(heat3, heatmap_var) * heat_weight
                    loss4_1 = criterion(vec4, vecmap_var) * vec_weight
                    loss4_2 = criterion(heat4, heatmap_var) * heat_weight
                    loss5_1 = criterion(vec5, vecmap_var) * vec_weight
                    loss5_2 = criterion(heat5, heatmap_var) * heat_weight
                    loss6_1 = criterion(vec6, vecmap_var) * vec_weight
                    loss6_2 = criterion(heat6, heatmap_var) * heat_weight
                    
                    loss = loss1_1 + loss1_2 + loss2_1 + loss2_2 + loss3_1 + loss3_2 + loss4_1 + loss4_2 + loss5_1 + loss5_2 + loss6_1 + loss6_2

                    losses.update(loss.item(), input.size(0))
                    for cnt, l in enumerate([loss1_1, loss1_2, loss2_1, loss2_2, loss3_1, loss3_2, loss4_1, loss4_2, loss5_1, loss5_2, loss6_1, loss6_2]):
                        losses_list[cnt].update(l.item(), input.size(0))
    
                batch_time.update(time.time() - end)
                end = time.time()
                is_best = losses.avg < best_model
                best_model = min(best_model, losses.avg)
                save_checkpoint({
                    'iter': iters,
                    'state_dict': model.state_dict(),
                    }, is_best, 'openpose_coco')
    
                print(
                    'Test Time {batch_time.sum:.3f}s, ({batch_time.avg:.3f})\t'
                    'Loss {loss.avg:.8f}\n'.format(
                    batch_time=batch_time, loss=losses))
                for cnt in range(0,12,2):
                    print('Loss{0}_1 = {loss1.val:.8f} (ave = {loss1.avg:.8f})\t'
                        'Loss{1}_2 = {loss2.val:.8f} (ave = {loss2.avg:.8f})'.format(cnt / 2 + 1, cnt / 2 + 1, loss1=losses_list[cnt], loss2=losses_list[cnt + 1]))
                print( time.strftime('%Y-%m-%d %H:%M:%S -----------------------------------------------------------------------------------------------------------------\n', time.localtime()))
    
                batch_time.reset()
                losses.reset()
                for cnt in range(12):
                    losses_list[cnt].reset()
                
                model.train()
    
            if iters == config.max_iter:
                break


if __name__ == '__main__':

    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    args = parse()
    model = construct_model(args)
    # model = None
    train_val(model, args)
