# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       16 |     86.74% |49-\>exit, 170, 220, 229, 250-\>245, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py               |     1268 |       62 |      540 |       53 |     93.42% |150, 164, 557, 563, 565-\>577, 621, 677, 686-\>688, 696, 699, 703-\>705, 706, 833, 842, 887, 976-980, 996, 1043, 1045, 1047, 1059-1062, 1067-\>1069, 1128, 1168, 1196, 1356, 1361, 1375, 1541-1542, 1592, 1599-\>1602, 1609, 1611-\>exit, 1721, 1745-\>1747, 1761, 1766, 1812-\>exit, 1830-\>1837, 1835-\>1837, 1853, 1881-\>1887, 1912-\>1918, 1916-\>1918, 1937, 1946-1948, 1989, 1997-\>exit, 2014-\>2020, 2021, 2033-2040, 2093, 2099-\>2101, 2127, 2141-2146, 2162-\>2165, 2171-2176, 2204-\>exit |
| src/aiogzip/\_codec\_async.py         |      123 |        1 |       28 |        1 |     98.68% |73-\>75, 192 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      171 |        1 |      104 |        6 |     97.45% |197, 294-\>exit, 301-\>exit, 308-\>exit, 309-\>exit, 310-\>exit |
| src/aiogzip/\_engine.py               |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       61 |        7 |       10 |        2 |     87.32% |74-75, 77, 90, 109-111 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       70 |        3 |       24 |        4 |     92.55% |20, 60-\>62, 63, 91 |
| src/aiogzip/\_source\_io.py           |       82 |        5 |       22 |        3 |     90.38% |31-33, 138, 145 |
| src/aiogzip/\_streaming.py            |      119 |        0 |       44 |        1 |     99.39% |219-\>exit |
| src/aiogzip/\_text.py                 |     1143 |       44 |      464 |       34 |     94.40% |439, 441, 471, 574, 609-611, 616, 628-630, 647-649, 660-\>exit, 686-\>exit, 693, 737, 744, 903, 938-\>941, 963, 988, 994-\>997, 1000, 1040, 1081-1085, 1087, 1101, 1152, 1252-1253, 1333, 1418-1419, 1431, 1651, 2099, 2114-\>2116, 2119-2122, 2160-\>exit, 2165-2167, 2210-\>exit, 2230, 2232-\>2235, 2236-\>exit |
| src/aiogzip/codec.py                  |      458 |        4 |      130 |        5 |     98.47% |62, 68-\>exit, 167, 186, 216-\>exit, 220-\>exit, 585 |
| **TOTAL**                             | **4805** |  **257** | **1782** |  **161** | **93.17%** |           |


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