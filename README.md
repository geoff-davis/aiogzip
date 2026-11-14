# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                  |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|-------------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| examples/concurrent\_jsonl\_ingest.py |      355 |       39 |       90 |       16 |     86.74% |49-\>exit, 170, 220, 229, 250-\>245, 287, 290, 311, 317, 384, 386, 422-\>exit, 452-453, 463-464, 481-493, 569, 572-\>580, 584-595, 599-605, 616-623 |
| examples/fragmented\_transport.py     |      326 |       69 |       62 |       10 |     78.09% |43-\>exit, 45-\>exit, 49-\>exit, 84, 99-101, 107, 134, 194, 201, 256, 260-261, 293-295, 315, 340, 369-373, 408-458, 462-470, 474-479, 487-489 |
| src/aiogzip/\_\_init\_\_.py           |       57 |        0 |       22 |        6 |     92.41% |132-\>exit, 153-\>exit, 171-\>exit, 216-\>exit, 237-\>exit, 255-\>exit |
| src/aiogzip/\_\_main\_\_.py           |       86 |        4 |       22 |        2 |     94.44% |34, 117, 120-121 |
| src/aiogzip/\_binary.py               |     1329 |       58 |      574 |       54 |     93.90% |154, 168, 496, 569, 575, 577-\>589, 644, 703, 712-\>714, 722, 725, 729-\>731, 732, 859, 868, 913, 1002-1006, 1024, 1071, 1073, 1075, 1087-1090, 1095-\>1097, 1156, 1196, 1227, 1387, 1392, 1406, 1608-\>exit, 1650-\>1653, 1660, 1662-\>exit, 1723-\>1726, 1726-\>exit, 1799, 1820-\>1822, 1836, 1841, 1872-\>1883, 1899-\>exit, 1927-\>1929, 1942, 1970-\>1976, 2008-\>2010, 2026, 2035-2037, 2078, 2086-\>exit, 2110, 2122-2129, 2182, 2188-\>2190, 2230-2235, 2251-\>2254, 2265-2268, 2306, 2331-\>exit |
| src/aiogzip/\_codec\_async.py         |      130 |        1 |       32 |        0 |     99.38% |       210 |
| src/aiogzip/\_codec\_buffer.py        |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py               |      175 |        1 |      108 |        7 |     97.17% |206, 303-\>exit, 310-\>exit, 317-\>exit, 318-\>exit, 319-\>exit, 332-\>exit |
| src/aiogzip/\_engine.py               |      111 |       16 |       60 |       12 |     81.29% |47, 92, 96, 103, 110-112, 115, 118-120, 167, 186, 198, 214, 227 |
| src/aiogzip/\_gzip\_header.py         |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py           |       95 |        2 |       26 |        3 |     95.87% |132, 148, 159-\>161 |
| src/aiogzip/\_metadata.py             |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_opening.py              |       92 |        2 |       38 |        2 |     96.92% |  121, 123 |
| src/aiogzip/\_source\_io.py           |       82 |        2 |       22 |        3 |     95.19% |31-\>33, 138, 145 |
| src/aiogzip/\_streaming.py            |      134 |        0 |       46 |        2 |     98.89% |247-\>250, 267-\>exit |
| src/aiogzip/\_text.py                 |     1203 |       40 |      490 |       36 |     94.92% |457, 459, 489, 601, 708-\>exit, 712-714, 719, 731-733, 753-755, 766-\>exit, 792-\>exit, 799, 843, 850, 975-\>exit, 1032, 1067-\>1070, 1092, 1117, 1123-\>1126, 1129, 1172, 1219-1223, 1225, 1239, 1290, 1390-1391, 1471, 1558-1559, 1571, 1791, 2241, 2263-\>2265, 2268-\>2270, 2271, 2315-\>exit, 2320-2322, 2365-\>exit, 2387-\>2390, 2391-\>exit |
| src/aiogzip/codec.py                  |      467 |        4 |      132 |        5 |     98.50% |67, 73-\>exit, 174, 193, 223-\>exit, 227-\>exit, 596 |
| **TOTAL**                             | **5062** |  **244** | **1894** |  **166** | **93.70%** |           |


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