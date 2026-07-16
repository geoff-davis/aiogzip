# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       58 |        0 |       22 |        6 |     92.50% |127-\>exit, 148-\>exit, 166-\>exit, 211-\>exit, 232-\>exit, 250-\>exit |
| src/aiogzip/\_binary.py     |      804 |       53 |      376 |       50 |     90.59% |330, 333, 339, 341-\>352, 378, 421, 430-\>432, 440, 443, 447-\>449, 450, 467, 542, 570, 572, 574, 578, 621, 643, 645, 653, 695, 699, 722, 724, 741, 743, 752-755, 759-762, 766-769, 776-\>exit, 902, 910, 1036, 1063-1064, 1116, 1142-\>1162, 1151-\>1155, 1158-1160, 1201, 1217, 1221, 1233, 1257, 1265, 1278, 1294, 1327-\>exit, 1329-\>exit, 1364-\>1374, 1375-\>exit, 1418-\>exit, 1421-\>exit |
| src/aiogzip/\_common.py     |      192 |        0 |      122 |        5 |     98.41% |324-\>exit, 331-\>exit, 338-\>exit, 339-\>exit, 340-\>exit |
| src/aiogzip/\_engine.py     |       43 |        4 |        8 |        4 |     84.31% |74, 86, 102, 115 |
| src/aiogzip/\_inspection.py |      297 |       14 |      112 |        9 |     94.38% |226, 230, 238, 240, 324, 344, 377, 458-459, 463, 467, 485-487 |
| src/aiogzip/\_streaming.py  |      194 |        0 |       66 |        1 |     99.62% |318-\>exit |
| src/aiogzip/\_text.py       |      784 |       53 |      342 |       32 |     91.21% |312-313, 339, 369, 380, 413-415, 420, 432-434, 451-453, 492, 499, 581, 615, 669, 694, 700-\>703, 706, 746, 787-791, 793, 807, 830-831, 836-\>839, 858, 864-\>867, 938-\>941, 943, 1039-1040, 1052, 1408, 1455, 1491-\>1493, 1496-1499, 1503-1507, 1537-\>exit, 1550, 1560-1562, 1566-1568 |
| **TOTAL**                   | **2372** |  **124** | **1048** |  **107** | **92.60%** |           |


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