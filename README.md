# 河岬监测数仓

河岬模拟环境监测站用这座数仓接纳仪器原件、核定读数和交班。站员登记计量标签及量程，质控员发布整版阈值并按固定输入巡核，交班负责人将整日巡核页结账。仪器重投可领取首次回执，同小时同值的不同原位逐条计量。次班换发阈值后，旧页和旧日结仍可领取。

## 运行

使用 Python 3.11 标准库。从项目根目录运行下列命令。`check_project.py` 由运行平台随项目入口提供。

```sh
python3 -B check_project.py
python3 -B warehouse.py demo
```

`demo` 创建隔离临时库、真实入仓和签发、关库再打开，核对手算结果后输出场景 JSON。检查或断言失败以非零状态退出。若要初始化一个日常使用的本地库，可执行 `python3 -B warehouse.py init rivercape.sqlite`。同一路径重复初始化会保留现有业务和同名站点配置，并补齐尚缺的样例站。

## 一天的账

1. 站员登记 `cape`，计量标签为 `mV`，允许读数从 −50 到 50，含两端。
2. 质控员为该站发布整版 A，唯一规则为 `[1,3)` 阈值 10，出处为 `(A, 0)`。
3. 仪器按原序提交 `(1, 10)`、`(2, 11)`、`(3, 11)`、`(4, None)`。回执含批接纳截点和四个零起算原位。原批重投领取相同回执。
4. 白班绑定本站、该截点、A 和 `[0,24)` 签页。四行按小时为正常、超限、无规则、缺测。头两行使用 `(A, 0)`。
5. 交班负责人用这份固定页签日结，正常、超限、无规则和缺测各一条。
6. 次班整版换发 B，唯一规则为 `[2,3)` 阈值 12。相同截点的新页得无规则、正常、无规则、缺测，新日结对应计数为 1、0、2、1。
7. 关库重开，按原号领取旧页、旧日结。另用 A 签页仍得到步骤 4 的四行。

| 小时 | 读数 | A 页判定 | B 页判定 |
| --- | --- | --- | --- |
| 1 | 10 | 正常，A 的位置 0 | 无规则 |
| 2 | 11 | 超限，A 的位置 0 | 正常，B 的位置 0 |
| 3 | 11 | 无规则 | 无规则 |
| 4 | 缺测 | 缺测 | 缺测 |

## Python 接口

```python
from warehouse import ObservationInput, ThresholdInterval, Warehouse

with Warehouse('rivercape.sqlite') as db:
    db.register_station('cape', 'mV', -50, 50)
    publication = db.publish_schedule('A', 'cape', [ThresholdInterval(1, 3, 10)])
    batch = db.ingest_batch('instrument-1', 'cape', 'mV', [
        ObservationInput(1, 10), ObservationInput(2, 11),
        ObservationInput(3, 11), ObservationInput(4, None),
    ])
    page = db.issue_rows('white-a', 'cape', batch.cutoff,
                         publication.revision.publication_id, 0, 24)
    close = db.close_day('shift-a', page.page_id)

with Warehouse('rivercape.sqlite') as db:
    assert db.get_review('white-a') == page
    assert db.get_day('shift-a') == close
```

- `register_station(code, unit, minimum, maximum)` 固定站点配置。同配置可重领。`bootstrap_stations()` 补齐样例。`get_station(code)` 按号取配置。
- `ingest_batch(batch_id, station, unit, rows)` 按原序接纳一组 `ObservationInput`，回执含 `cutoff` 和原观测。批号全库唯一。站点、单位、原序小时和读数共同确定是否是原批重投。批次即使没有观测也可领取回执。`get_batch` 查询原批，`latest_cutoff` 查询全库最新接纳序号。截点 0 表示空采样输入。
- `publish_schedule(publication_id, station, intervals)` 接收一组 `ThresholdInterval`，返回 `revision` 与 `current_head`。发布号全库唯一。起点含、终点不含，区间可以相邻，空区间和交叠拒绝，空列表发布全站无规则版。规则出处保留输入原位。旧版原内容重投领取原修订，`current_head` 仍是当下生效的版。`get_head(station)` 返回当前发布号或 `None`，`get_revision(station, revision)` 返回指定历史修订，`threshold_at(station, revision, hour)` 返回命中规则或 `None`。
- `issue_rows(page_id, station, cutoff, revision, start, end)` 用固定截点及指定本地修订签页。记录以整数小时、接纳序号、批内原位排序。巡核页只保存实际观测行及该行使用的阈值和出处。`get_review(page_id)` 领取原页。`list_observations(station, cutoff, start, end)` 按同一采样选择口径查原观测。
- `issue_review(page_id, station, revision, start, end)` 签发整窗凭据页：首次成功时固定当时的 `latest_cutoff()` 与指定修订，返回与 `issue_rows` 同形的 `binding`、`rows`，并附 `coverage` —— 按起点升序、首尾相接覆盖整窗的 `(start, end, threshold, source)` 元组，无采样或无规则的时段以 `(None, None)` 显式空档列出。同一页号以相同站点、修订和窗重投返回首发结果及原截点；异参数或跨签发入口占号抛 `ValueError`。`revision` 可指定历史修订。旧接口签发的页没有 `coverage`，不能作为更正凭据。
- `amend_review(request_id, page_id, edits)` 凭整窗凭据页提交有序 `(start, end, threshold)` 编辑，阈值为非负整数或 `None`（清除）。编辑须在页窗内、宽度为正、互不重叠。提交时按页站点的同一现行修订核对每个待改小时的实际阈值与出处（发布号与发布内位置；两个无规则状态相同），有差异抛 `ValueError` 并在 `conflict_hour` 给出最早冲突小时。成功返回 `PublicationReceipt`，`revision` 为整条有效修订，`current_head` 为本次发布号：未编辑段沿用原出处，设置段以本次发布号及零起算输入位置为出处，清除段读作无规则。同号、同页、同有序编辑重投返回首次回执；异申请与提及已占发布号抛 `ValueError`。`request_id` 与 `publish_schedule` 共用全库发布号空间。
- `close_day(close_id, page_id)` 仅接受对齐的整日窗 `[24×日序,24×(日序+1))`。它核对固定页的来源和日窗，汇总 `normal`、`exceeded`、`unruled`、`missing`。`get_day(close_id)` 领取日结及所引页号。完整空日页可签零计数日结。凭据页同样可结账，结账按页绑定的修订与固定行，不受作答后目录前进影响。

## 口径和失败边界

标识及单位标签为非空字符串，首尾无空白，单位标签逐字匹配。小时、实测读数和值域端点使用整数，阈值为非负整数。所有领域整数精确存取，SQLite 中用整数的十六进制文本保全任意精度，数值比较及排序按解码后的整数执行。`None` 表示缺测，读数 0 按实测核定。缺测优先，实测落在规则空档列为无规则，有规则的读数严格大于阈值才超限。相同输入、截点和修订会得到同一逐行口径。

输入非法、同号异内容以及引用异站修订时抛出 `ValueError`。未知站、批、修订、页或日结抛出 `KeyError`。批头及原位、目录修订及头、巡核页头及明细分别原子提交，日结号及计数同次提交。提交前故障回滚本次写入，已签历史仍可读，失败标识可重试。需要同时打开同一库时，各值班进程应使用自己的 `Warehouse` 连接。

原回归覆盖样例重复初始化、单位和闭量程准入、重投和重复出现、相邻阈值的原位、换版回滚、固定截点、半开规则边界和日界、异站修订、整版换发后重开及日结故障重试。

凭页更正约定：`issue_review` 在首次成功签发时固定 `latest_cutoff()`、指定修订和整窗 `coverage`（含无采样时段与显式无规则空档）。`amend_review` 的「现行修订」取提交前该站点的 `get_head`，逐小时比较阈值、发布号与发布内位置；两个无规则状态视为相同，日间后来出现的观测不参与比较。成功提交把整条有效修订、现行头和回执放在同一次 SQLite 写入，失败回滚且不占号；未编辑段保留实际原出处，设置段以 `request_id` 为发布号、零起算输入位置为位置。已签页、历史修订、日结和更正回执按原号可领取，后续 `publish_schedule` 或重开都不改动它们。
