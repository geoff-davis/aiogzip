# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       16 |     86.74% |49-\>exit, 170, 220, 229, 250-\>245, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       57 |        0 |       22 |        6 |     92.41% |132-\>exit, 153-\>exit, 171-\>exit, 232-\>exit, 253-\>exit, 271-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       86 |        4 |       22 |        2 |     94.44% |34, 117, 120-121 |
| src/aiogzip/\_binary.py               |     1367 |       57 |      580 |       53 |     94.14% |161, 175, 587, 666, 668-\>695, 750, 809, 818-\>820, 828, 831, 835-\>837, 838, 965, 974, 1019, 1108-1112, 1130, 1177, 1179, 1181, 1194-1199, 1204-\>1206, 1269, 1309, 1383, 1543, 1548, 1562, 1774-\>exit, 1816-\>1819, 1826, 1828-\>exit, 1889-\>1892, 1892-\>exit, 1965, 1986-\>1988, 2002, 2007, 2038-\>2050, 2066-\>exit, 2099-\>2101, 2114, 2142-\>2148, 2180-\>2182, 2198, 2207-2209, 2250, 2258-\>exit, 2282, 2294-2301, 2354, 2360-\>2362, 2402-2407, 2423-\>2426, 2437-2440, 2478, 2503-\>exit |
| src/aiogzip/\_codec\_async.py         |      144 |        1 |       34 |        0 |     99.44% |       243 |
| src/aiogzip/\_codec\_buffer.py        |      231 |        6 |       90 |        8 |     95.64% |28, 73-\>exit, 116, 118, 133, 137, 216, 297-\>exit |
| src/aiogzip/\_common.py               |      231 |        7 |      126 |        9 |     95.52% |167, 170, 182-184, 193-195, 322, 419-\>exit, 426-\>exit, 433-\>exit, 434-\>exit, 435-\>exit, 448-\>exit |
| src/aiogzip/\_engine.py               |      111 |       16 |       60 |       12 |     81.29% |47, 92, 96, 103, 110-112, 115, 118-120, 167, 186, 198, 214, 227 |
| src/aiogzip/\_gzip\_header.py         |      215 |        1 |       90 |        1 |     99.34% |        77 |
| src/aiogzip/\_inspection.py           |      104 |        2 |       28 |        3 |     96.21% |145, 161, 174-\>176 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       97 |        2 |       38 |        2 |     97.04% |  128, 130 |
| src/aiogzip/\_source\_io.py           |       82 |        2 |       22 |        3 |     95.19% |31-\>33, 138, 145 |
| src/aiogzip/\_streaming.py            |      134 |        0 |       46 |        2 |     98.89% |247-\>250, 267-\>exit |
| src/aiogzip/\_text.py                 |     1214 |       40 |      492 |       36 |     94.96% |555, 557, 587, 699, 806-\>exit, 810-812, 817, 829-831, 851-853, 864-\>exit, 890-\>exit, 897, 941, 948, 1090-\>exit, 1147, 1182-\>1185, 1207, 1232, 1238-\>1241, 1244, 1287, 1334-1338, 1340, 1354, 1405, 1505-1506, 1586, 1673-1674, 1686, 1906, 2356, 2382-\>2384, 2388-\>2390, 2391, 2435-\>exit, 2440-2442, 2485-\>exit, 2507-\>2510, 2511-\>exit |
| src/aiogzip/codec.py                  |      494 |        5 |      148 |        6 |     98.29% |80, 86-\>exit, 187, 206, 236-\>exit, 240-\>exit, 629, 662 |
| **TOTAL**                             | **5258** |  **251** | **1950** |  **169** | **93.78%** |           |


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