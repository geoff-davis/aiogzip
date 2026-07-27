# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                           |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|------------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py    |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py    |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py        |      775 |       66 |      362 |       50 |     89.27% |371, 374, 380, 382-\>393, 419, 462, 471-\>473, 481, 484, 488-\>490, 491, 508, 583, 611, 613, 615, 619, 662, 684, 686, 694, 736, 740, 763, 765, 782, 784, 793-796, 800-803, 807-810, 817-\>exit, 863, 911, 1037, 1042, 1060, 1063-1065, 1072-1075, 1128, 1132, 1144, 1157-\>1159, 1171, 1179, 1192, 1208, 1244, 1249-\>exit, 1251-\>exit, 1284, 1292-\>exit, 1307-1314, 1334, 1340-\>1342, 1353-\>exit, 1356-\>exit |
| src/aiogzip/\_codec\_async.py  |       93 |        7 |       18 |        1 |     92.79% |64-67, 68-\>73, 71-72, 141 |
| src/aiogzip/\_codec\_buffer.py |      202 |        5 |       82 |        7 |     95.77% |28, 57-\>exit, 98, 100, 115, 119, 240-\>exit |
| src/aiogzip/\_common.py        |      192 |        1 |      122 |        6 |     97.77% |183, 324-\>exit, 331-\>exit, 338-\>exit, 339-\>exit, 340-\>exit |
| src/aiogzip/\_engine.py        |      107 |       15 |       58 |       11 |     81.82% |81, 85, 92, 99-101, 104, 107-109, 156, 175, 187, 203, 216 |
| src/aiogzip/\_gzip\_header.py  |      208 |        1 |       88 |        1 |     99.32% |        57 |
| src/aiogzip/\_inspection.py    |       60 |        7 |       10 |        2 |     87.14% |72-73, 75, 88, 107-109 |
| src/aiogzip/\_metadata.py      |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_streaming.py     |      100 |        0 |       42 |        2 |     98.59% |87-\>65, 184-\>exit |
| src/aiogzip/\_text.py          |      803 |       52 |      348 |       30 |     91.66% |327-328, 382, 412, 423, 456-458, 463, 475-477, 494-496, 535, 542, 624, 658, 712, 737, 743-\>746, 749, 789, 830-834, 836, 850, 873-874, 901, 907-\>910, 981-\>984, 986, 1082-1083, 1095, 1451, 1584-\>1586, 1589-1592, 1596-1600, 1630-\>exit, 1643, 1653-1655, 1659-1661 |
| src/aiogzip/codec.py           |      414 |        6 |      114 |        7 |     97.54% |61, 67-\>exit, 116, 136, 155, 185-\>exit, 189-\>exit, 326, 514 |
| **TOTAL**                      | **3066** |  **161** | **1280** |  **124** | **92.89%** |           |


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