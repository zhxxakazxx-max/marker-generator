Fabric Label Batch Generator v1.0

用途
====
从 Excel 的 C 列读取成分，为每条有效成分生成全部 12 种颜色。

输出结构
========
每种中文成分一个文件夹，每个文件夹包含：
浅蓝.png、宝蓝.png、米白.png、藏青.png、湖蓝.png、黑色.png、绿色.png、
酒红.png、白色.png、灰色.png、红色.png、橙色.png。

运行规则
========
1. 每次 API 请求至少间隔 10 秒。
2. HTTP 408、429、5xx、超时和连接失败会自动重试；每个任务最多尝试 3 次。
3. 达到 3 次后显示失败，点击“重试全部失败”可为失败任务开启新一轮 3 次尝试。
4. 关闭程序后，重新用相同 Excel 和输出目录启动，会读取 batch-progress.json 并从断点继续。
5. 已存在且有效的 PNG 会被识别为完成，不会重复生成。

数据文件
========
batch-progress.json：全部任务状态和断点进度。
failed-tasks.json：完成一轮后仍失败的任务。
import-errors.json：Excel 中无法解析的行。

API 密钥不会写入上述进度文件；程序读取 Fabric Label Studio 已保存的本机设置。
