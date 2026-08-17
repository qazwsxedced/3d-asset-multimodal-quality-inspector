# Resume-Ready Contributions

## 中文版本

### 多图与结构化元数据融合的 3D 资产质量检查研究与工程原型

PyTorch、Qwen2.5-VL-3B、QLoRA/PEFT、Blender 5.2、Gradio

- 独立设计并实现 Blender 3D 资产质检数据管线，覆盖 5 类资产、6 类拓扑/UV/法线缺陷，生成 600 条多视角、UV/法线诊断图及结构化几何统计样本，并按场景级划分训练/验证/测试集。
- 构建 B0-B4 控制变量实验协议，完成 Qwen2.5-VL-3B 零样本推理、4-bit QLoRA 微调、JSON/schema 校验、多标签 Macro-F1、分组泛化和错误案例分析；三随机种子 B4 缺陷 Macro-F1 达到 `82.55% ± 0.72%`。
- 实现 metadata-only Rule baseline 与 Rule/VLM/Hybrid review 三种质检策略，在 28 个外部 `.blend` 验证资产上实现 100% Blender 预处理成功率；Hybrid 对分歧样本自动路由人工复核。
- 开发 `.blend` 上传和批量处理 Demo，支持 Blender 后台预处理、失败重试、结构化日志、P50/P95 耗时统计及 JSON/HTML 审计报告。

### 面试中应主动说明

- 600 条数据和 28 个外部验证资产均为受控研究/验证数据，不等同于客户生产数据。
- 当前系统定位为工业导向原型，规则检测是安全门禁，VLM 用于多模态解释和修复建议。

## English version

### Multimodal 3D Asset Quality Inspection Research and Engineering Prototype

PyTorch, Qwen2.5-VL-3B, QLoRA/PEFT, Blender 5.2, Gradio

- Independently built a Blender-based 3D asset inspection data pipeline covering five asset families and six topology/UV/normal defect types, producing 600 multi-view samples with UV/normal diagnostics and structured geometry metadata under scene-level splits.
- Designed a controlled B0-B4 ablation protocol and implemented Qwen2.5-VL-3B zero-shot inference, 4-bit QLoRA fine-tuning, JSON/schema validation, multi-label Macro-F1, grouped generalization, and error analysis; three B4 seeds achieved `82.55% ± 0.72%` defect Macro-F1.
- Implemented metadata-only Rule baseline and Rule/VLM/Hybrid review policies; on 28 external `.blend` validation fixtures, Blender preprocessing succeeded for 28/28 assets and disagreement cases were automatically routed to human review.
- Developed a local `.blend` upload and batch-processing demo with Blender background preprocessing, configurable retries, structured logs, P50/P95 timing, and auditable JSON/HTML reports.

### Interview-safe framing

- The 600-sample benchmark and 28 external fixtures are controlled research/validation data, not customer-production data.
- The system is an industrial-oriented prototype: deterministic geometry rules remain the safety gate, while the VLM provides multimodal interpretation and repair suggestions.
