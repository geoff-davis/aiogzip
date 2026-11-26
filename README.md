# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       16 |     86.74% |49-\>exit, 170, 220, 229, 250-\>245, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       63 |        0 |       22 |        6 |     92.94% |134-\>exit, 155-\>exit, 173-\>exit, 234-\>exit, 255-\>exit, 273-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       86 |        4 |       22 |        2 |     94.44% |34, 117, 120-121 |
| src/aiogzip/\_binary.py               |     1363 |       57 |      578 |       53 |     94.13% |160, 174, 575, 654, 656-\>683, 738, 797, 806-\>808, 816, 819, 823-\>825, 826, 953, 962, 1007, 1096-1100, 1118, 1165, 1167, 1169, 1182-1187, 1192-\>1194, 1257, 1297, 1371, 1531, 1536, 1550, 1762-\>exit, 1804-\>1807, 1814, 1816-\>exit, 1877-\>1880, 1880-\>exit, 1953, 1974-\>1976, 1990, 1995, 2026-\>2038, 2054-\>exit, 2087-\>2089, 2102, 2130-\>2136, 2168-\>2170, 2186, 2195-2197, 2238, 2246-\>exit, 2270, 2282-2289, 2342, 2348-\>2350, 2390-2395, 2411-\>2414, 2425-2428, 2466, 2491-\>exit |
| src/aiogzip/\_codec\_async.py         |      144 |        1 |       34 |        0 |     99.44% |       243 |
| src/aiogzip/\_codec\_buffer.py        |      231 |        6 |       90 |        8 |     95.64% |28, 73-\>exit, 116, 118, 133, 137, 216, 297-\>exit |
| src/aiogzip/\_common.py               |      231 |        7 |      126 |        9 |     95.52% |167, 170, 182-184, 193-195, 322, 419-\>exit, 426-\>exit, 433-\>exit, 434-\>exit, 435-\>exit, 448-\>exit |
| src/aiogzip/\_engine.py               |      126 |       17 |       64 |       13 |     82.11% |48, 93, 97, 104, 111-113, 116, 119-121, 168, 187, 199, 215, 228, 284 |
| src/aiogzip/\_gzip\_header.py         |      215 |        1 |       90 |        1 |     99.34% |        77 |
| src/aiogzip/\_inspection.py           |      104 |        2 |       28 |        3 |     96.21% |145, 161, 174-\>176 |
| src/aiogzip/\_iterable\_reader.py     |      121 |        0 |       54 |        1 |     99.43% | 226-\>228 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_oneshot.py              |       37 |        0 |       10 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       97 |        2 |       38 |        2 |     97.04% |  128, 130 |
| src/aiogzip/\_source\_io.py           |       82 |        2 |       22 |        3 |     95.19% |31-\>33, 138, 145 |
| src/aiogzip/\_streaming.py            |      128 |        0 |       44 |        2 |     98.84% |234-\>237, 254-\>exit |
| src/aiogzip/\_text.py                 |     1218 |       40 |      494 |       36 |     94.98% |571, 573, 603, 715, 822-\>exit, 826-828, 833, 845-847, 867-869, 880-\>exit, 906-\>exit, 913, 957, 964, 1106-\>exit, 1163, 1198-\>1201, 1223, 1248, 1254-\>1257, 1260, 1303, 1350-1354, 1356, 1370, 1421, 1521-1522, 1602, 1689-1690, 1702, 1922, 2372, 2398-\>2400, 2404-\>2406, 2407, 2451-\>exit, 2456-2458, 2501-\>exit, 2523-\>2526, 2527-\>exit |
| src/aiogzip/codec.py                  |      537 |        6 |      168 |        7 |     98.16% |80, 86-\>exit, 187, 206, 236-\>exit, 240-\>exit, 622, 655, 947 |
| **TOTAL**                             | **5474** |  **253** | **2036** |  **172** | **93.97%** |           |


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