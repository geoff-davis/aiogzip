# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       19 |        0 |       10 |        0 |    100.00% |           |
| src/aiogzip/\_binary.py     |      662 |       54 |      320 |       55 |     88.70% |166, 230, 287, 290, 296, 298-\>309, 333, 376, 382, 390, 393, 397-\>399, 400, 415, 438, 441, 449, 451, 453, 456, 487, 489, 492, 502, 504, 506, 508, 525-526, 548-551, 554, 577, 579, 590, 596, 598, 617, 702, 716, 831, 855-856, 929, 945, 949, 961, 969, 984, 992, 1005, 1021, 1043, 1047-\>1052, 1049-\>1052, 1079-\>1083, 1084-\>exit, 1091, 1127-\>exit, 1130-\>exit |
| src/aiogzip/\_common.py     |      170 |        0 |      108 |        5 |     98.20% |280-\>exit, 287-\>exit, 294-\>exit, 295-\>exit, 296-\>exit |
| src/aiogzip/\_engine.py     |       30 |        3 |        6 |        3 |     83.33% |52, 72, 85 |
| src/aiogzip/\_text.py       |      648 |       45 |      302 |       32 |     91.05% |151, 167, 257-258, 275, 287-291, 303, 314, 346-348, 351-353, 370-372, 411, 477, 511, 552, 559, 565-\>568, 571, 611, 652-656, 658, 672, 694-695, 700-\>703, 722, 728-\>731, 801-\>804, 806, 902-903, 915, 1012, 1158, 1171-1172, 1195, 1286-\>exit, 1297-\>exit |
| **TOTAL**                   | **1529** |  **102** |  **746** |   **95** | **90.90%** |           |


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