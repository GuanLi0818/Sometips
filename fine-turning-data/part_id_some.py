# -*- coding: utf-8 -*-
"""
@File    : part_id_some.py
@Author  : qy
@Date    : 2025/10/15 17:23
"""
import os
import json

with open("part_id.txt", "r") as f:
    part_id = f.readlines()
    part_id = [i.strip() for i in part_id]
    print(len(part_id))