# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                           |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py    |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py    |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py        |     1053 |       65 |      462 |       58 |     91.75% |105, 119, 439, 446-447, 517, 523, 525-\>537, 577, 633, 642-\>644, 652, 655, 659-\>661, 662, 761, 789, 795, 798, 843, 875, 889, 923, 927, 932-936, 952, 996, 998, 1000, 1002, 1012-1015, 1020-\>1022, 1027-1028, 1081, 1150, 1301, 1306, 1316, 1321-1322, 1440, 1442-\>1445, 1452, 1454-\>exit, 1536, 1540, 1552, 1565-\>1567, 1582, 1590, 1603, 1655, 1660-\>exit, 1662-\>exit, 1686, 1694-\>exit, 1707-\>1715, 1731-1738, 1767, 1773-\>1775, 1788, 1797, 1810-\>1815, 1821-\>exit, 1823-\>exit |
| src/aiogzip/\_codec\_async.py  |       93 |        7 |       18 |        1 |     92.79% |64-67, 68-\>73, 71-72, 141 |
| src/aiogzip/\_codec\_buffer.py |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py        |      163 |        1 |      100 |        6 |     97.34% |183, 280-\>exit, 287-\>exit, 294-\>exit, 295-\>exit, 296-\>exit |
| src/aiogzip/\_engine.py        |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py  |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py    |       60 |        7 |       10 |        2 |     87.14% |72-73, 75, 88, 107-109 |
| src/aiogzip/\_metadata.py      |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_streaming.py     |      100 |        0 |       42 |        2 |     98.59% |87-\>65, 184-\>exit |
| src/aiogzip/\_text.py          |     1078 |       81 |      436 |       48 |     90.29% |391-392, 412-413, 487, 498, 533-535, 540, 552-554, 571-573, 584-\>exit, 607-\>exit, 614, 658, 665, 761, 765-766, 786, 823, 855-860, 882, 907, 913-\>916, 919, 959, 1000-1004, 1006, 1020, 1039-1040, 1068, 1103-1105, 1139, 1159-1160, 1230-\>1233, 1235, 1246-1247, 1251-1252, 1314-1315, 1327, 1501, 1542, 1544, 1735, 1745, 1749, 1950, 1962-\>1964, 1967-1970, 1975-1977, 2008-\>exit, 2013-2015, 2033-2035, 2054-\>exit, 2073-2077, 2080-\>exit |
| src/aiogzip/codec.py           |      451 |        4 |      130 |        5 |     98.45% |61, 67-\>exit, 165, 184, 214-\>exit, 218-\>exit, 571 |
| **TOTAL**                      | **3627** |  **187** | **1462** |  **148** | **92.95%** |           |


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