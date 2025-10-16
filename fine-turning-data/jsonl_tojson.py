# -*- coding: utf-8 -*-
"""
@File    : jsonl_tojson.py
@Author  : qy
@Date    : 2025/10/15 15:07
"""
import json
import os

def jsonl_tojson(jsonl_path, json_path):
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    data = [json.loads(line) for line in lines]


    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    jsonl_path = 'finetune_samples.jsonl'
    json_path = 'data.json'
    jsonl_tojson(jsonl_path, json_path)