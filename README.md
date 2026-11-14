# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       16 |     86.74% |49-\>exit, 170, 220, 229, 250-\>245, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       57 |        0 |       22 |        6 |     92.41% |132-\>exit, 153-\>exit, 171-\>exit, 216-\>exit, 237-\>exit, 255-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       86 |        4 |       22 |        2 |     94.44% |34, 117, 120-121 |
| src/aiogzip/\_binary.py               |     1354 |       57 |      580 |       53 |     94.11% |158, 172, 500, 579, 581-\>608, 663, 722, 731-\>733, 741, 744, 748-\>750, 751, 878, 887, 932, 1021-1025, 1043, 1090, 1092, 1094, 1107-1112, 1117-\>1119, 1182, 1222, 1296, 1456, 1461, 1475, 1677-\>exit, 1719-\>1722, 1729, 1731-\>exit, 1792-\>1795, 1795-\>exit, 1868, 1889-\>1891, 1905, 1910, 1941-\>1952, 1968-\>exit, 1996-\>1998, 2011, 2039-\>2045, 2077-\>2079, 2095, 2104-2106, 2147, 2155-\>exit, 2179, 2191-2198, 2251, 2257-\>2259, 2299-2304, 2320-\>2323, 2334-2337, 2375, 2400-\>exit |
| src/aiogzip/\_codec\_async.py         |      144 |        1 |       34 |        0 |     99.44% |       243 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      175 |        1 |      108 |        7 |     97.17% |206, 303-\>exit, 310-\>exit, 317-\>exit, 318-\>exit, 319-\>exit, 332-\>exit |
| src/aiogzip/\_engine.py               |      111 |       16 |       60 |       12 |     81.29% |47, 92, 96, 103, 110-112, 115, 118-120, 167, 186, 198, 214, 227 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       95 |        2 |       26 |        3 |     95.87% |132, 148, 159-\>161 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       92 |        2 |       38 |        2 |     96.92% |  121, 123 |
| src/aiogzip/\_source\_io.py           |       82 |        2 |       22 |        3 |     95.19% |31-\>33, 138, 145 |
| src/aiogzip/\_streaming.py            |      134 |        0 |       46 |        2 |     98.89% |247-\>250, 267-\>exit |
| src/aiogzip/\_text.py                 |     1214 |       40 |      492 |       36 |     94.96% |458, 460, 490, 602, 709-\>exit, 713-715, 720, 732-734, 754-756, 767-\>exit, 793-\>exit, 800, 844, 851, 993-\>exit, 1050, 1085-\>1088, 1110, 1135, 1141-\>1144, 1147, 1190, 1237-1241, 1243, 1257, 1308, 1408-1409, 1489, 1576-1577, 1589, 1809, 2259, 2285-\>2287, 2291-\>2293, 2294, 2338-\>exit, 2343-2345, 2388-\>exit, 2410-\>2413, 2414-\>exit |
| src/aiogzip/codec.py                  |      467 |        4 |      132 |        5 |     98.50% |67, 73-\>exit, 174, 193, 223-\>exit, 227-\>exit, 596 |
| **TOTAL**                             | **5112** |  **243** | **1904** |  **165** | **93.79%** |           |


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