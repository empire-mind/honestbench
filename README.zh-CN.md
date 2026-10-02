# honestbench — 衡量验证过程而非仅仅关注通过率的评测框架

[English](README.md) | 简体中文

每个基准测试都会告诉你通过还是失败。HonestBench 提出了一个更苛刻的问题：**智能体在声称完成任务之前是否真正进行了*验证*？** 它审查执行轨迹（trajectory），而不仅仅是补丁——因为基准测试中约 10% 的“通过”纯属侥幸（盲目重试、缺失验证步骤、无序探索）。

## 状态：可用基础，研究路线图

目前已交付的系统及其组合：

1. **`evals/`** — 离线优先的检索/记忆评测框架。适配器契约（`init` → `query` → 排序文档）、带有黄金标准答案键的问题族、结构化防作弊（适配器接收剥离了答案键的盲测查询——即使意外也*无法*读取答案键）、机器可读的计分卡以及逐题凭证（receipts）。运行全程零 API 调用。
2. **`code-factory/`** — 评测运行的加固执行平面：超时控制、全进程组 SIGKILL 终止、环境清理、工作目录限制（cwd jail）、网络隔离、64 KiB 输出截断上限、`runs/<run-id>/` 证据持久化。10/10 项测试全部通过（详见 `code-factory/tests/TEST-LOG.md`）。

下一步计划 — 实际的侥幸通过检测器（Lucky-pass detector，轨迹审计：盲目重试、缺失验证、回归循环、无序探索检测器，并发布精确率/召回率指标）。这是 `help wanted` Issue 中规划的研究路线图。评测框架与执行平面是其所需的基础底座；它们现在已经正常工作。

## 60 秒快速演示（零 API 调用，无需额外安装）

```bash
git clone https://github.com/empire-mind/honestbench.git
cd honestbench/evals
python3 run.py --adapter grep-only --queries all
```

你将在 `evals/reports/` 下获得一份计分卡和逐题凭证：

```
adapter=grep-only top_k=5 n=6
  recall_all@5: 0.6
  first_hit@5: 0.6
  mean_rank_first: 1.0
  abstention_accuracy: 0.0
```

同样可以尝试执行平面：

```bash
cd ../code-factory
./factory run --language python --timeout 10 - <<'EOF'
print("hello from the factory")
EOF
```

## 设计原则

- **分母分离。** 检索能力与答案正确性分别独立测量；在某一个问题族上的良好得分仅是深入研究的理由，而非对所有工作负载的通用保证。
- **适配器无法作弊。** 运行器在适配器看到查询之前，在结构层面剔除了黄金标注（gold labels）。
- **凭证为凭，杜绝凭感觉。** 每次运行都会输出包含架构版本、配置卡片和语料库哈希的机器可读计分卡。如果无法复现，就视同没有发生。
- **如实记录局限性。** `code-factory/CODE-FACTORY.md` 书面记录了执行平面*尚未*实现的功能（尚无文件系统沙箱、静默后端降级）。我们在此保持这种诚实文化。

## 目录结构

```
honestbench/
  evals/            评测框架：run.py, adapters/, data/, STAGE-NEXT.md
  code-factory/     执行平面：factory CLI + factory.py
  examples/         hello-eval 示例演示
```

## 开发

```bash
cd evals && python3 run.py --adapter grep-only   # 框架冒烟测试
cd ../code-factory && ./factory backends          # 执行平面后端探测
```

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 贡献指南

**每个 Issue 和外部 PR 都会在 7 个自然日内获得首次回复。** `good first issue` 任务设计为一个晚上即可完成；侥幸通过检测器（lucky-pass detector）的工作属于 `help wanted`，诚挚欢迎研究助力。完整流程详见 [CONTRIBUTING.md](CONTRIBUTING.md)。
安全问题报告：请阅读组织的 [SECURITY.md](https://github.com/empire-mind/.github/blob/main/SECURITY.md)。

## 致谢

评测方法改编自 [garrytan/gbrain-evals](https://github.com/garrytan/gbrain-evals) (BrainBench)，MIT © 2026 Garry Tan —— 借鉴其架构思想，代码完全自主原创。
详见 `evals/README.md` 与 `evals/STAGE-NEXT.md`。

## 许可证

MIT — 详见 [LICENSE](LICENSE)。
