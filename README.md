# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       17 |     86.52% |49-\>exit, 170, 220, 229, 250-\>245, 284-\>288, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       49 |        1 |       16 |        1 |     96.92% |        23 |
| src/aiogzip/\_binary.py               |     1329 |       58 |      574 |       55 |     93.85% |152, 166, 489, 562, 568, 570-\>582, 637, 693, 702-\>704, 712, 715, 719-\>721, 722, 849, 858, 903, 992-996, 1014, 1061, 1063, 1065, 1077-1080, 1085-\>1087, 1146, 1186, 1217, 1377, 1382, 1396, 1598-\>exit, 1640-\>1643, 1650, 1652-\>exit, 1713-\>1716, 1716-\>exit, 1789, 1810-\>1812, 1826, 1831, 1862-\>1873, 1889-\>exit, 1917-\>1919, 1932, 1960-\>1966, 1998-\>2000, 2016, 2025-2027, 2068, 2076-\>exit, 2093-\>2099, 2100, 2112-2119, 2172, 2178-\>2180, 2220-2225, 2241-\>2244, 2255-2258, 2296, 2321-\>exit |
| src/aiogzip/\_codec\_async.py         |      129 |        1 |       32 |        0 |     99.38% |       209 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      173 |        1 |      106 |        6 |     97.49% |202, 299-\>exit, 306-\>exit, 313-\>exit, 314-\>exit, 315-\>exit |
| src/aiogzip/\_engine.py               |      111 |       16 |       60 |       12 |     81.29% |47, 92, 96, 103, 110-112, 115, 118-120, 167, 186, 198, 214, 227 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       90 |        2 |       24 |        3 |     95.61% |117, 130, 141-\>143 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       92 |        2 |       38 |        2 |     96.92% |  121, 123 |
| src/aiogzip/\_source\_io.py           |       82 |        2 |       22 |        3 |     95.19% |31-\>33, 138, 145 |
| src/aiogzip/\_streaming.py            |      119 |        0 |       42 |        1 |     99.38% |233-\>exit |
| src/aiogzip/\_text.py                 |     1203 |       40 |      490 |       36 |     94.92% |449, 451, 481, 593, 700-\>exit, 704-706, 711, 723-725, 742-744, 755-\>exit, 781-\>exit, 788, 832, 839, 964-\>exit, 1021, 1056-\>1059, 1081, 1106, 1112-\>1115, 1118, 1161, 1208-1212, 1214, 1228, 1279, 1379-1380, 1460, 1547-1548, 1560, 1780, 2230, 2252-\>2254, 2257-\>2259, 2260, 2304-\>exit, 2309-2311, 2354-\>exit, 2376-\>2379, 2380-\>exit |
| src/aiogzip/codec.py                  |      467 |        4 |      132 |        5 |     98.50% |67, 73-\>exit, 174, 193, 223-\>exit, 227-\>exit, 596 |
| **TOTAL**                             | **5004** |  **241** | **1880** |  **165** | **93.70%** |           |


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