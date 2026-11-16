# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       17 |     86.52% |49-\>exit, 170, 220, 229, 250-\>245, 284-\>288, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       57 |        0 |       22 |        6 |     92.41% |132-\>exit, 153-\>exit, 171-\>exit, 232-\>exit, 253-\>exit, 271-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       86 |        4 |       22 |        2 |     94.44% |34, 117, 120-121 |
| src/aiogzip/\_binary.py               |     1364 |       57 |      580 |       53 |     94.14% |160, 174, 576, 655, 657-\>684, 739, 798, 807-\>809, 817, 820, 824-\>826, 827, 954, 963, 1008, 1097-1101, 1119, 1166, 1168, 1170, 1183-1188, 1193-\>1195, 1258, 1298, 1372, 1532, 1537, 1551, 1763-\>exit, 1805-\>1808, 1815, 1817-\>exit, 1878-\>1881, 1881-\>exit, 1954, 1975-\>1977, 1991, 1996, 2027-\>2039, 2055-\>exit, 2088-\>2090, 2103, 2131-\>2137, 2169-\>2171, 2187, 2196-2198, 2239, 2247-\>exit, 2271, 2283-2290, 2343, 2349-\>2351, 2391-2396, 2412-\>2415, 2426-2429, 2467, 2492-\>exit |
| src/aiogzip/\_codec\_async.py         |      144 |        1 |       34 |        0 |     99.44% |       243 |
| src/aiogzip/\_codec\_buffer.py        |      231 |        6 |       90 |        8 |     95.64% |28, 73-\>exit, 116, 118, 133, 137, 216, 297-\>exit |
| src/aiogzip/\_common.py               |      231 |        7 |      126 |        9 |     95.52% |167, 170, 182-184, 193-195, 322, 419-\>exit, 426-\>exit, 433-\>exit, 434-\>exit, 435-\>exit, 448-\>exit |
| src/aiogzip/\_engine.py               |      126 |       17 |       64 |       13 |     82.11% |48, 93, 97, 104, 111-113, 116, 119-121, 168, 187, 199, 215, 228, 284 |
| src/aiogzip/\_gzip\_header.py         |      215 |        1 |       90 |        1 |     99.34% |        77 |
| src/aiogzip/\_inspection.py           |      104 |        2 |       28 |        3 |     96.21% |145, 161, 174-\>176 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       97 |        2 |       38 |        2 |     97.04% |  128, 130 |
| src/aiogzip/\_source\_io.py           |       82 |        2 |       22 |        3 |     95.19% |31-\>33, 138, 145 |
| src/aiogzip/\_streaming.py            |      128 |        0 |       44 |        2 |     98.84% |234-\>237, 254-\>exit |
| src/aiogzip/\_text.py                 |     1219 |       40 |      496 |       36 |     94.99% |572, 574, 604, 716, 823-\>exit, 827-829, 834, 846-848, 868-870, 881-\>exit, 907-\>exit, 914, 958, 965, 1107-\>exit, 1164, 1199-\>1202, 1224, 1249, 1255-\>1258, 1261, 1304, 1351-1355, 1357, 1371, 1422, 1522-1523, 1603, 1690-1691, 1703, 1923, 2373, 2399-\>2401, 2405-\>2407, 2408, 2452-\>exit, 2457-2459, 2502-\>exit, 2524-\>2527, 2528-\>exit |
| src/aiogzip/codec.py                  |      491 |        5 |      148 |        6 |     98.28% |74, 80-\>exit, 181, 200, 230-\>exit, 234-\>exit, 616, 649 |
| **TOTAL**                             | **5266** |  **252** | **1956** |  **171** | **93.76%** |           |


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