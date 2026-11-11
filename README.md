# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       17 |     86.52% |49-\>exit, 170, 220, 229, 250-\>245, 284-\>288, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       49 |        1 |       16 |        1 |     96.92% |        23 |
| src/aiogzip/\_binary.py               |     1327 |       58 |      572 |       55 |     93.84% |152, 166, 489, 562, 568, 570-\>582, 637, 693, 702-\>704, 712, 715, 719-\>721, 722, 849, 858, 903, 992-996, 1012, 1059, 1061, 1063, 1075-1078, 1083-\>1085, 1144, 1184, 1215, 1375, 1380, 1394, 1596-\>exit, 1638-\>1641, 1648, 1650-\>exit, 1711-\>1714, 1714-\>exit, 1787, 1808-\>1810, 1824, 1829, 1860-\>1871, 1887-\>exit, 1915-\>1917, 1930, 1958-\>1964, 1996-\>1998, 2014, 2023-2025, 2066, 2074-\>exit, 2091-\>2097, 2098, 2110-2117, 2170, 2176-\>2178, 2218-2223, 2239-\>2242, 2253-2256, 2294, 2319-\>exit |
| src/aiogzip/\_codec\_async.py         |      129 |        1 |       32 |        0 |     99.38% |       209 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      171 |        1 |      104 |        6 |     97.45% |200, 297-\>exit, 304-\>exit, 311-\>exit, 312-\>exit, 313-\>exit |
| src/aiogzip/\_engine.py               |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       90 |        2 |       24 |        3 |     95.61% |117, 130, 141-\>143 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       92 |        2 |       38 |        2 |     96.92% |  121, 123 |
| src/aiogzip/\_source\_io.py           |       82 |        2 |       22 |        3 |     95.19% |31-\>33, 138, 145 |
| src/aiogzip/\_streaming.py            |      121 |        0 |       44 |        1 |     99.39% |227-\>exit |
| src/aiogzip/\_text.py                 |     1190 |       40 |      480 |       36 |     94.85% |447, 449, 479, 588, 686-\>exit, 690-692, 697, 709-711, 728-730, 741-\>exit, 767-\>exit, 774, 818, 825, 950-\>exit, 1007, 1042-\>1045, 1067, 1092, 1098-\>1101, 1104, 1144, 1185-1189, 1191, 1205, 1256, 1356-1357, 1437, 1522-1523, 1535, 1755, 2203, 2225-\>2227, 2230-\>2232, 2233, 2277-\>exit, 2282-2284, 2327-\>exit, 2349-\>2352, 2353-\>exit |
| src/aiogzip/codec.py                  |      465 |        4 |      132 |        5 |     98.49% |62, 68-\>exit, 169, 188, 218-\>exit, 222-\>exit, 589 |
| **TOTAL**                             | **4983** |  **240** | **1866** |  **164** | **93.69%** |           |


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