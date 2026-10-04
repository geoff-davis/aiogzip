# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       17 |     86.52% |49-\>exit, 170, 220, 229, 250-\>245, 284-\>288, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py               |     1151 |       66 |      500 |       57 |     92.43% |115, 129, 497-498, 568, 574, 576-\>588, 628, 684, 693-\>695, 703, 706, 710-\>712, 713, 812, 840, 846, 849, 894, 926, 940, 978, 983-987, 1003, 1047, 1049, 1051, 1053, 1063-1066, 1071-\>1073, 1078-1079, 1132, 1201, 1352, 1357, 1367, 1372-1373, 1486, 1493-\>1496, 1503, 1505-\>exit, 1588, 1592, 1604, 1619-\>1621, 1636, 1641, 1685-\>exit, 1703-\>1710, 1708-\>1710, 1726, 1751-\>1757, 1801, 1809-\>exit, 1822-\>1830, 1846-1853, 1886, 1892-\>1894, 1907, 1920, 1935-\>1938, 1944-1949, 1966-\>exit, 1968-\>exit |
| src/aiogzip/\_codec\_async.py         |      123 |        1 |       28 |        1 |     98.68% |73-\>75, 192 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      171 |        1 |      104 |        6 |     97.45% |197, 294-\>exit, 301-\>exit, 308-\>exit, 309-\>exit, 310-\>exit |
| src/aiogzip/\_engine.py               |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       61 |        7 |       10 |        2 |     87.32% |74-75, 77, 90, 109-111 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       70 |        3 |       24 |        4 |     92.55% |20, 60-\>62, 63, 91 |
| src/aiogzip/\_source\_io.py           |       81 |        6 |       22 |        3 |     87.38% |31-33, 132-133, 140 |
| src/aiogzip/\_streaming.py            |      119 |        0 |       44 |        1 |     99.39% |219-\>exit |
| src/aiogzip/\_text.py                 |     1132 |       67 |      458 |       46 |     91.89% |413, 415, 443, 541, 576-578, 583, 595-597, 614-616, 627-\>exit, 650-\>exit, 657, 701, 708, 804, 808-809, 829, 834-836, 866, 900-\>903, 925, 950, 956-\>959, 962, 1002, 1043-1047, 1049, 1063, 1066-\>1075, 1111, 1146-1148, 1211-1212, 1282-\>1285, 1287, 1303-1304, 1366-1367, 1379, 1597, 1599, 1785, 1795, 1799, 2060, 2072-\>2074, 2077-2080, 2085-2087, 2118-\>exit, 2123-2125, 2168-\>exit, 2187-2191, 2194-\>exit |
| src/aiogzip/codec.py                  |      458 |        4 |      130 |        5 |     98.47% |62, 68-\>exit, 166, 185, 215-\>exit, 219-\>exit, 583 |
| **TOTAL**                             | **4676** |  **285** | **1736** |  **178** | **92.22%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/geoff-davis/aiogzip/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/geoff-davis/aiogzip/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fgeoff-davis%2Faiogzip%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.