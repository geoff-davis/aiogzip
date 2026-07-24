# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                          |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|------------------------------ | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py   |       59 |        0 |       22 |        6 |     92.59% |128-\>exit, 149-\>exit, 167-\>exit, 212-\>exit, 233-\>exit, 251-\>exit |
| src/aiogzip/\_\_main\_\_.py   |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py       |      781 |       66 |      366 |       50 |     89.36% |374, 377, 383, 385-\>396, 422, 465, 474-\>476, 484, 487, 491-\>493, 494, 511, 586, 614, 616, 618, 622, 665, 687, 689, 697, 739, 743, 766, 768, 785, 787, 796-799, 803-806, 810-813, 820-\>exit, 866, 916, 1042, 1047, 1065, 1068-1070, 1077-1080, 1146, 1150, 1162, 1175-\>1177, 1189, 1197, 1210, 1226, 1262, 1267-\>exit, 1269-\>exit, 1302, 1310-\>exit, 1325-1332, 1352, 1358-\>1360, 1371-\>exit, 1374-\>exit |
| src/aiogzip/\_codec\_async.py |       61 |        6 |       10 |        2 |     88.73% |36-39, 40-\>45, 43-44, 75-\>79 |
| src/aiogzip/\_common.py       |      192 |        1 |      122 |        6 |     97.77% |183, 324-\>exit, 331-\>exit, 338-\>exit, 339-\>exit, 340-\>exit |
| src/aiogzip/\_engine.py       |       99 |       11 |       44 |       11 |     84.62% |93, 101, 105, 109, 125, 144, 149, 163, 175, 191, 204 |
| src/aiogzip/\_inspection.py   |       60 |        7 |       10 |        2 |     87.14% |72-73, 75, 82, 101-103 |
| src/aiogzip/\_metadata.py     |       10 |        0 |        0 |        0 |    100.00% |           |
| src/aiogzip/\_streaming.py    |       90 |        0 |       36 |        1 |     99.21% |162-\>exit |
| src/aiogzip/\_text.py         |      803 |       52 |      348 |       30 |     91.66% |327-328, 382, 412, 423, 456-458, 463, 475-477, 494-496, 535, 542, 624, 658, 712, 737, 743-\>746, 749, 789, 830-834, 836, 850, 873-874, 901, 907-\>910, 981-\>984, 986, 1082-1083, 1095, 1451, 1584-\>1586, 1589-1592, 1596-1600, 1630-\>exit, 1643, 1653-1655, 1659-1661 |
| src/aiogzip/codec.py          |      403 |        2 |      134 |        5 |     98.70% |75, 103-\>exit, 131-\>exit, 135-\>exit, 578 |
| **TOTAL**                     | **2601** |  **146** | **1106** |  **114** | **92.45%** |           |


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