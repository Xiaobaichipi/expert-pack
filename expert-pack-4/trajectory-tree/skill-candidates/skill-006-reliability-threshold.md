# Skill 候选：reliability_threshold

## 元数据
- **ID**: skill-006
- **意图族**: reliability_threshold
- **状态**: draft
- **成功样本**: 0
- **生成候选**: 1
- **提炼时间**: 2026-11-16T07:44:06+00:00

## 触发条件
- 查询 STA-220-07 负载率最高的主变型号，只回答型号。

## 推荐动作序列
```
tool:pms/query_outage_incident
```

## 示例答案
```
（待验证）
```

## 审核清单
- [ ] 动作序列是否覆盖所有必要步骤？
- [ ] 是否有遗漏的异常分支？
- [ ] 参数是否可移植（stationId/assetId 等）？
- [ ] 是否需要补充边界条件？
