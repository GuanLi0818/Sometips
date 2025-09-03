# -*- coding: utf-8 -*-
"""
@File    : company_info.py
@Author  : qy
@Date    : 2025/7/29 13:21
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class CompanyInfo(BaseModel):

    name: str = Field(..., description="公司名称，必填")

    org: Optional[str] = Field(None, description="企业组织形式")
    cap: Optional[str] = Field(None, description="企业资本类型")
    size: Optional[str] = Field(None, description="企业规模")
    description: Optional[str] = Field(None, description="企业简介")
    establish_time: Optional[str] = Field(None, description="企业成立时间")
    regist_loc: Optional[str] = Field(None, description="注册地址")
    tax_loc: Optional[str] = Field(None, description="税收户管地")
    person_size: Optional[int] = Field(None, description="企业员工人数")
    cap_size: Optional[float] = Field(None, description="企业注册资金（万元）")
    credit_rating: Optional[List[str]] = Field(default_factory=list, description="企业信用等级")
    credit_code : Optional[str] =Field(None, description="统一社会信用代码")


    industry: Optional[List[str]] = Field(default_factory=list, description="所属行业")
    primary_product: Optional[List[str]] = Field(default_factory=list, description="主营业务")
    key_focus_areas: Optional[List[str]] = Field(default_factory=list, description="重点领域")
    honors: Optional[List[str]] = Field(default_factory=list, description="荣誉资质")
    qualifications: Optional[List[str]] = Field(default_factory=list, description="企业资质")
    rank: Optional[List[str]] = Field(default_factory=list, description="企业称号")
    tags: Optional[List[str]] = Field(default_factory=list, description="其他标签")


    r_d_staff_count: Optional[int] = Field(None, description="研发人员人数")
    revenue_last_year: Optional[float] = Field(None, description="上一年营收（万元）")
    revenue_growth_rate_last_year: Optional[float] = Field(None, description="上年营收增幅（%）")
    r_d_expense_last_year: Optional[float] = Field(None, description="上年研发支出（万元）")
    total_profit_last_year: Optional[float] = Field(None, description="上年利润（万元）")
    total_assets_last_year: Optional[float] = Field(None, description="上年总资产（万元）")
    asset_liability_ratio_last_year: Optional[float] = Field(None, description="上年资产负债率（%）")
    total_output_last_year: Optional[float] = Field(None, description="上年总产值（万元）")



