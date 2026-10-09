# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       16 |     86.74% |49-\>exit, 170, 220, 229, 250-\>245, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       49 |        1 |       16 |        1 |     96.92% |        23 |
| src/aiogzip/\_binary.py               |     1303 |       60 |      558 |       54 |     93.66% |151, 165, 558, 564, 566-\>578, 626, 682, 691-\>693, 701, 704, 708-\>710, 711, 838, 847, 892, 981-985, 1001, 1048, 1050, 1052, 1064-1067, 1072-\>1074, 1133, 1173, 1201, 1361, 1366, 1380, 1579-\>exit, 1614, 1621-\>1624, 1631, 1633-\>exit, 1694-\>1697, 1697-\>exit, 1770, 1794-\>1796, 1810, 1815, 1861-\>exit, 1889-\>1891, 1904, 1932-\>1938, 1970-\>1972, 1988, 1997-1999, 2040, 2048-\>exit, 2065-\>2071, 2072, 2084-2091, 2144, 2150-\>2152, 2192-2197, 2213-\>2216, 2222-2227, 2255, 2280-\>exit |
| src/aiogzip/\_codec\_async.py         |      123 |        1 |       28 |        0 |     99.34% |       192 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      171 |        1 |      104 |        6 |     97.45% |200, 297-\>exit, 304-\>exit, 311-\>exit, 312-\>exit, 313-\>exit |
| src/aiogzip/\_engine.py               |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       92 |        2 |       26 |        4 |     94.92% |115, 128, 139-\>141, 161-\>163 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       72 |        2 |       24 |        3 |     94.79% |67-\>69, 70, 98 |
| src/aiogzip/\_source\_io.py           |       82 |        5 |       22 |        3 |     90.38% |31-33, 138, 145 |
| src/aiogzip/\_streaming.py            |      119 |        0 |       44 |        1 |     99.39% |219-\>exit |
| src/aiogzip/\_text.py                 |     1171 |       40 |      474 |       35 |     94.83% |446, 448, 478, 581, 679-\>exit, 683-685, 690, 702-704, 721-723, 734-\>exit, 760-\>exit, 767, 811, 818, 977, 1012-\>1015, 1037, 1062, 1068-\>1071, 1074, 1114, 1155-1159, 1161, 1175, 1226, 1326-1327, 1407, 1492-1493, 1505, 1725, 2173, 2194-\>2196, 2199-\>2201, 2202, 2246-\>exit, 2251-2253, 2296-\>exit, 2318-\>2321, 2322-\>exit |
| src/aiogzip/codec.py                  |      458 |        4 |      130 |        5 |     98.47% |62, 68-\>exit, 167, 186, 216-\>exit, 220-\>exit, 585 |
| **TOTAL**                             | **4907** |  **245** | **1828** |  **163** | **93.50%** |           |


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