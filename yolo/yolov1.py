# -*- coding: utf-8 -*-
"""
Created on Fri Mar 16 14:38:10 2018

@author: vl-tshzzz
"""
import torch
import torch.nn as nn
from yolo.decoder import yolo_decoder
from yolo.darknet import darknet_19,conv_block,fill_fc_weights
from yolo.loss import yolov1_loss


def create_yolov1_model(cfg):
    cls_num = cfg['class_num']
    box_num = cfg['box_num']
    ceil_size = cfg['ceil_size']
    pretrained = cfg['pretrained']
    l_coord = cfg['l_coord']
    l_noobj = cfg['l_noobj']
    l_obj = cfg['l_obj']
    conv_mode = cfg['conv_mode']
    model = YOLO(cls_num,box_num,ceil_size,pretrained,l_coord,l_obj,l_noobj,conv_mode)

    return model




class YOLO(nn.Module):

    def __init__(self, cls_num, bbox_num=2, scale_size=7,
                 pretrained=None,
                 l_coord=5,
                 l_obj=1,
                 l_noobj=0.5,
                 conv_mode=False
                 ):
        super(YOLO, self).__init__()

        self.cls_num = cls_num
        self.conv_mode = conv_mode
        self.backbone = darknet_19()
        if pretrained is not None:
            self.backbone.load_weight(pretrained)

        self.loss = yolov1_loss(l_coord,l_obj, l_noobj)
        self.scale_size = scale_size
        self.bbox_num = bbox_num
        self.last_output = (5 * self.bbox_num + self.cls_num)

        self.local_layer = nn.Sequential()
        self.local_layer.add_module('block_1', conv_block(1024, 1024, 3, False, 2))
        self.local_layer.add_module('block_2', conv_block(1024, 1024, 3, False, 1))
        self.local_layer.add_module('block_3', conv_block(1024, 1024, 3, False, 1))
        self.local_layer.add_module('block_4', conv_block(1024, 1024, 3, False, 1))
        fill_fc_weights(self.local_layer)

        if not self.conv_mode:
            self.reg_layer = nn.Sequential()
            self.reg_layer.add_module('local_layer', nn.Linear(1024 * 7 * 7, 4096))
            self.reg_layer.add_module('leaky_local', nn.LeakyReLU(0.1, inplace=True))
            self.reg_layer.add_module('dropout', nn.Dropout(0.5))
            fill_fc_weights(self.reg_layer)
            self.cls_pred =  nn.Linear(4096, self.cls_num * self.scale_size * self.scale_size)
            self.response_pred = nn.Linear(4096, self.bbox_num * self.scale_size * self.scale_size)
            self.offset_pred = nn.Linear(4096, self.bbox_num * 4 * self.scale_size * self.scale_size)
        else:
            self.cls_pred = nn.Sequential(
                                    nn.Conv2d(1024,256,3,stride=1, padding=1),
                                    nn.ReLU(),
                                    nn.Conv2d(256, self.cls_num, 1, stride=1, padding=0)
            )
            self.response_pred = nn.Sequential(
                                    nn.Conv2d(1024,256,3,stride=1, padding=1),
                                    nn.ReLU(),
                                    nn.Conv2d(256, self.bbox_num , 1, stride=1, padding=0)
            )
            self.offset_pred = nn.Sequential(
                                    nn.Conv2d(1024,256,3,stride=1, padding=1),
                                    nn.ReLU(),
                                    nn.Conv2d(256, self.bbox_num * 4, 1, stride=1, padding=0)
            )

        fill_fc_weights(self.cls_pred)
        fill_fc_weights(self.response_pred)
        fill_fc_weights(self.offset_pred)

    def gen_anchor(self,ceil):

        anchor_list = []
        w,h = ceil

        x = torch.linspace(1, w, w).unsqueeze(dim=0).repeat(h, 1).unsqueeze(dim=0)
        y = torch.linspace(1, h, h).unsqueeze(dim=0).repeat(w, 1).unsqueeze(dim=0).permute(0, 2, 1)
        width = torch.Tensor([1]).view(1, 1, 1).repeat(1, h, w)
        height = torch.Tensor([1]).view(1, 1, 1).repeat(1, h, w)
        anchor_list.append(torch.cat((x, y, width, height), dim=0).unsqueeze(dim=0))

        anchor = torch.cat(anchor_list, dim=0)
        anchor = anchor.view(-1, h, w).repeat(2,1,1)

        return anchor

    def forward(self, x, target=None,conf=0.02, topk=100, nms_threshold=0.5):

        B, c, h, w = x.shape
        img_size = (w,h)
        device = x.get_device()
        output = self.backbone(x)
        output = self.local_layer(output)

        B,c,ceil_h,ceil_w = output.shape
        ceil = (ceil_w,ceil_h)
        anchor = self.gen_anchor(ceil).repeat(B,1,1,1).to(device)

        if self.conv_mode:
            pred_cls = self.cls_pred(output)
            pred_response = self.response_pred(output)
            pred_bbox = self.offset_pred(output)
        else:
            output = output.view(B,-1)
            output = self.reg_layer(output)
            pred_cls = self.cls_pred(output).view(B,self.cls_num,self.scale_size,self.scale_size)
            pred_response = self.response_pred(output).view(B,self.bbox_num,self.scale_size,self.scale_size)
            pred_bbox = self.offset_pred(output).view(B,self.bbox_num*4,self.scale_size,self.scale_size)

        pred_bbox += anchor
        if target is None:
            output = []
            for bs in range(B):
                cls = pred_cls[bs,:,:,:]
                objness = pred_response[bs,:,:,:]
                bbox = pred_bbox[bs,:,:,:]
                pred = (cls,objness,bbox)
                output.append(yolo_decoder(pred,img_size,conf,topk,nms_threshold))
            return output
        else:
            pred = (pred_cls,pred_response,pred_bbox)
            loss_dict = self.loss(pred,target)
            return loss_dict



if __name__ == '__main__':
    from data.datasets import VOCDatasets
    net = YOLO(20).cuda()
    #net.load_state_dict(torch.load('tmp_test.pth'))
    input = torch.zeros(1, 3, 448, 448).cuda()
    dataset = VOCDatasets('./train.txt',train=False)
    data = net(input,[dataset[110]])
    print(data)
    #tmp = net.state_dict()
    #torch.save(tmp,'tmp_test.pth')



