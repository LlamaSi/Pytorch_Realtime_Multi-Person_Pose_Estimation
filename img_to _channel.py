
def label_2_onhot(b_parsing_tensor, parsing_label_nc=20):
    size = b_parsing_tensor.size()
    oneHot_size = (parsing_label_nc, size[1], size[2])
    b_parsing_label = torch.cuda.FloatTensor(torch.Size(oneHot_size)).zero_()
    b_parsing_label = b_parsing_label.scatter_(0, b_parsing_tensor.long().cuda(), 1.0)

    return b_parsing_label

