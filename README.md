# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       58 |        0 |       22 |        6 |     92.50% |127-\>exit, 148-\>exit, 166-\>exit, 211-\>exit, 232-\>exit, 250-\>exit |
| src/aiogzip/\_\_main\_\_.py |       43 |        1 |       14 |        1 |     96.49% |        22 |
| src/aiogzip/\_binary.py     |      810 |       53 |      376 |       50 |     90.64% |358, 361, 367, 369-\>380, 406, 449, 458-\>460, 468, 471, 475-\>477, 478, 495, 570, 598, 600, 602, 606, 649, 671, 673, 681, 723, 727, 750, 752, 769, 771, 780-783, 787-790, 794-797, 804-\>exit, 930, 938, 1064, 1091-1092, 1144, 1170-\>1190, 1179-\>1183, 1186-1188, 1229, 1245, 1249, 1261, 1285, 1293, 1306, 1322, 1355-\>exit, 1357-\>exit, 1392-\>1402, 1403-\>exit, 1446-\>exit, 1449-\>exit |
| src/aiogzip/\_common.py     |      192 |        0 |      122 |        5 |     98.41% |324-\>exit, 331-\>exit, 338-\>exit, 339-\>exit, 340-\>exit |
| src/aiogzip/\_engine.py     |       44 |        4 |        8 |        4 |     84.62% |77, 89, 105, 118 |
| src/aiogzip/\_inspection.py |      297 |       14 |      112 |        9 |     94.38% |226, 230, 238, 240, 324, 344, 377, 458-459, 463, 467, 485-487 |
| src/aiogzip/\_streaming.py  |      194 |        0 |       66 |        1 |     99.62% |318-\>exit |
| src/aiogzip/\_text.py       |      803 |       52 |      348 |       30 |     91.66% |326-327, 381, 411, 422, 455-457, 462, 474-476, 493-495, 534, 541, 623, 657, 711, 736, 742-\>745, 748, 788, 829-833, 835, 849, 872-873, 900, 906-\>909, 980-\>983, 985, 1081-1082, 1094, 1450, 1583-\>1585, 1588-1591, 1595-1599, 1629-\>exit, 1642, 1652-1654, 1658-1660 |
| **TOTAL**                   | **2441** |  **124** | **1068** |  **106** | **92.82%** |           |


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