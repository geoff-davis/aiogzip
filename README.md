# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       29 |        0 |       16 |        3 |     93.33% |116-\>exit, 137-\>exit, 155-\>exit |
| src/aiogzip/\_binary.py     |      805 |       53 |      376 |       50 |     90.60% |331, 334, 340, 342-\>353, 379, 422, 431-\>433, 441, 444, 448-\>450, 451, 468, 543, 571, 573, 575, 579, 622, 644, 646, 654, 696, 700, 723, 725, 742, 744, 753-756, 760-763, 767-770, 777-\>exit, 903, 911, 1037, 1064-1065, 1117, 1143-\>1163, 1152-\>1156, 1159-1161, 1202, 1218, 1222, 1234, 1258, 1266, 1279, 1295, 1328-\>exit, 1330-\>exit, 1365-\>1375, 1376-\>exit, 1419-\>exit, 1422-\>exit |
| src/aiogzip/\_common.py     |      192 |        0 |      122 |        5 |     98.41% |324-\>exit, 331-\>exit, 338-\>exit, 339-\>exit, 340-\>exit |
| src/aiogzip/\_engine.py     |       30 |        3 |        6 |        3 |     83.33% |52, 72, 85 |
| src/aiogzip/\_text.py       |      727 |       52 |      316 |       31 |     90.70% |299-300, 326, 356, 367, 400-402, 407, 419-421, 438-440, 479, 486, 568, 602, 656, 681, 687-\>690, 693, 733, 774-778, 780, 794, 817-818, 823-\>826, 845, 851-\>854, 925-\>928, 930, 1026-1027, 1039, 1310, 1390-\>1392, 1395-1398, 1402-1406, 1436-\>exit, 1449, 1459-1461, 1465-1467 |
| **TOTAL**                   | **1783** |  **108** |  **836** |   **92** | **91.52%** |           |


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