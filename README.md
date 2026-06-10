# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       29 |        0 |       16 |        3 |     93.33% |116-\>exit, 137-\>exit, 155-\>exit |
| src/aiogzip/\_binary.py     |      702 |       50 |      338 |       51 |     90.10% |176, 257, 321, 324, 330, 332-\>343, 367, 410, 416, 424, 427, 431-\>433, 434, 451, 525, 552, 554, 556, 559, 602, 623, 625, 627, 629, 646-647, 669-672, 675, 698, 700, 711, 717, 719, 738, 823, 837, 946, 970-971, 1044, 1060, 1064, 1076, 1084, 1099, 1107, 1120, 1136, 1169-\>exit, 1171-\>exit, 1198-\>1202, 1203-\>exit, 1210, 1246-\>exit, 1249-\>exit |
| src/aiogzip/\_common.py     |      181 |        0 |      112 |        5 |     98.29% |310-\>exit, 317-\>exit, 324-\>exit, 325-\>exit, 326-\>exit |
| src/aiogzip/\_engine.py     |       30 |        3 |        6 |        3 |     83.33% |52, 72, 85 |
| src/aiogzip/\_text.py       |      657 |       45 |      298 |       32 |     91.10% |162, 178, 290-291, 315, 327-331, 343, 354, 387-389, 392-394, 411-413, 452, 518, 552, 606, 631, 637-\>640, 643, 683, 724-728, 730, 744, 767-768, 773-\>776, 795, 801-\>804, 875-\>878, 880, 976-977, 989, 1087, 1233, 1246-1247, 1270, 1361-\>exit, 1372-\>exit |
| **TOTAL**                   | **1599** |   **98** |  **770** |   **94** | **91.47%** |           |


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