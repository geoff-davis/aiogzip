# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      294 |       36 |       64 |       11 |     85.75% |46-\>exit, 167, 217, 226, 233, 300, 302, 352-353, 363-364, 381-393, 469, 472-\>480, 484-495, 499-505, 516-523 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py               |     1056 |       65 |      462 |       58 |     91.77% |107, 121, 447, 454-455, 525, 531, 533-\>545, 585, 641, 650-\>652, 660, 663, 667-\>669, 670, 769, 797, 803, 806, 851, 883, 897, 931, 935, 940-944, 960, 1004, 1006, 1008, 1010, 1020-1023, 1028-\>1030, 1035-1036, 1089, 1158, 1309, 1314, 1324, 1329-1330, 1448, 1450-\>1453, 1460, 1462-\>exit, 1544, 1548, 1560, 1573-\>1575, 1590, 1598, 1611, 1663, 1668-\>exit, 1670-\>exit, 1694, 1702-\>exit, 1715-\>1723, 1739-1746, 1775, 1781-\>1783, 1796, 1805, 1818-\>1823, 1829-\>exit, 1831-\>exit |
| src/aiogzip/\_codec\_async.py         |       93 |        7 |       18 |        1 |     92.79% |64-67, 68-\>73, 71-72, 141 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      171 |        1 |      104 |        6 |     97.45% |197, 294-\>exit, 301-\>exit, 308-\>exit, 309-\>exit, 310-\>exit |
| src/aiogzip/\_engine.py               |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       61 |        7 |       10 |        2 |     87.32% |74-75, 77, 90, 109-111 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_streaming.py            |      102 |        0 |       42 |        2 |     98.61% |88-\>66, 187-\>exit |
| src/aiogzip/\_text.py                 |     1081 |       81 |      436 |       48 |     90.31% |399-400, 420-421, 495, 506, 541-543, 548, 560-562, 579-581, 592-\>exit, 615-\>exit, 622, 666, 673, 769, 773-774, 794, 831, 863-868, 890, 915, 921-\>924, 927, 967, 1008-1012, 1014, 1028, 1047-1048, 1076, 1111-1113, 1147, 1167-1168, 1238-\>1241, 1243, 1254-1255, 1259-1260, 1322-1323, 1335, 1509, 1550, 1552, 1743, 1753, 1757, 1958, 1970-\>1972, 1975-1978, 1983-1985, 2016-\>exit, 2021-2023, 2041-2043, 2062-\>exit, 2081-2085, 2088-\>exit |
| src/aiogzip/codec.py                  |      458 |        4 |      130 |        5 |     98.47% |62, 68-\>exit, 166, 185, 215-\>exit, 219-\>exit, 583 |
| **TOTAL**                             | **4271** |  **292** | **1592** |  **169** | **91.56%** |           |


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