# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       17 |     86.52% |49-\>exit, 170, 220, 229, 250-\>245, 284-\>288, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py               |     1280 |       62 |      544 |       55 |     93.37% |150, 164, 557, 563, 565-\>577, 625, 681, 690-\>692, 700, 703, 707-\>709, 710, 837, 846, 891, 980-984, 1000, 1047, 1049, 1051, 1063-1066, 1071-\>1073, 1132, 1172, 1200, 1360, 1365, 1379, 1545-1546, 1596, 1603-\>1606, 1613, 1615-\>exit, 1676-\>1679, 1679-\>exit, 1752, 1776-\>1778, 1792, 1797, 1843-\>exit, 1861-\>1868, 1866-\>1868, 1884, 1912-\>1918, 1943-\>1949, 1947-\>1949, 1968, 1977-1979, 2020, 2028-\>exit, 2045-\>2051, 2052, 2064-2071, 2124, 2130-\>2132, 2158, 2172-2177, 2193-\>2196, 2202-2207, 2235-\>exit |
| src/aiogzip/\_codec\_async.py         |      123 |        1 |       28 |        1 |     98.68% |73-\>75, 192 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      171 |        1 |      104 |        6 |     97.45% |197, 294-\>exit, 301-\>exit, 308-\>exit, 309-\>exit, 310-\>exit |
| src/aiogzip/\_engine.py               |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       74 |        2 |       22 |        4 |     93.75% |86, 99, 110-\>112, 132-\>134 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       70 |        2 |       24 |        3 |     94.68% |60-\>62, 63, 91 |
| src/aiogzip/\_source\_io.py           |       82 |        5 |       22 |        3 |     90.38% |31-33, 138, 145 |
| src/aiogzip/\_streaming.py            |      119 |        0 |       44 |        1 |     99.39% |219-\>exit |
| src/aiogzip/\_text.py                 |     1166 |       44 |      472 |       35 |     94.44% |446, 448, 478, 581, 679-\>exit, 683-685, 690, 702-704, 721-723, 734-\>exit, 760-\>exit, 767, 811, 818, 977, 1012-\>1015, 1037, 1062, 1068-\>1071, 1074, 1114, 1155-1159, 1161, 1175, 1226, 1326-1327, 1407, 1492-1493, 1505, 1725, 2173, 2188-\>2190, 2193-2196, 2234-\>exit, 2239-2241, 2284-\>exit, 2304, 2306-\>2309, 2310-\>exit |
| src/aiogzip/codec.py                  |      458 |        4 |      130 |        5 |     98.47% |62, 68-\>exit, 167, 186, 216-\>exit, 220-\>exit, 585 |
| **TOTAL**                             | **4853** |  **251** | **1806** |  **166** | **93.26%** |           |


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