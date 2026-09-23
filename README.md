# Agent Loop

一个用于构建和运行 AI Agent 循环的项目。Agent 根据任务获取上下文、调用工具并持续迭代，直到完成目标或达到停止条件。

## 核心流程

1. 接收用户任务
2. 分析当前状态并制定下一步行动
3. 调用模型或外部工具
4. 更新上下文并循环执行
5. 返回最终结果

## 开始使用

```bash
git clone <repository-url>
cd agent-loop
python main.py
```
