#!/usr/bin/env python3
"""LAVIS离线入口：构建训练标签、训练并按独立来源验证；不读取最终测试。"""
import argparse
import os
from pathlib import Path
import sys
# 在导入数值库前限制线程；训练和标准实验不要并行抢资源。
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ.setdefault(name,'1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from algorithms.lavis.training import build_dataset,train

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['dataset','train'])
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--extra-dataset',type=Path,help='已按家族冻结的独立高冲突数据根目录')
    parser.add_argument('--states',type=int,default=10)
    parser.add_argument('--model-id',default='lavis-v1')
    parser.add_argument('--budget',type=float,default=15.)
    parser.add_argument('--no-augmentation',action='store_true')
    args=parser.parse_args()
    if not 2<=args.states<=40:parser.error('states需要在2到40之间')
    if args.limit is not None and not 1<=args.limit<=200:parser.error('limit需要在1到200之间')
    if not .2<args.budget<=600:parser.error('budget需要大于0.2且不超过600')
    if args.command=='dataset':build_dataset(args.dataset,args.output,args.limit,args.states,extra_dataset=args.extra_dataset)
    else:train(args.dataset,args.output,args.model_id,args.budget,not args.no_augmentation,extra_dataset=args.extra_dataset)

if __name__=='__main__':main()
