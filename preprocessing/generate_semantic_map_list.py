

semap_root = '/home/wenwens/Datasets/DeepFashion/img/'
import glob,os.path
filesDepth3 = glob.glob(dataroot + '*/*/*')
dirsDepth3 = filter(lambda f: os.path.isdir(f), filesDepth3)

import pdb

for id_path in tqdm(dirsDepth3):
    json_path = id_path.replace('img', 'img_parsing_all')
    if not os.path.isdir(json_path):
        os.makedirs(json_path)
    imgs = os.listdir(id_path)
    for img in tqdm(imgs):
        if len(img) > 3:
            
            img_path = os.path.join(id_path, img)
            inference(net=net, img_path=img_path,output_path=json_path , output_name=img, use_gpu=use_gpu)