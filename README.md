# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/geoff-davis/aiogzip/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                        |    Stmts |     Miss |   Branch |   BrPart |      Cover |   Missing |
|---------------------------- | -------: | -------: | -------: | -------: | ---------: | --------: |
| src/aiogzip/\_\_init\_\_.py |       29 |        0 |       16 |        3 |     93.33% |116-\>exit, 137-\>exit, 155-\>exit |
| src/aiogzip/\_binary.py     |      717 |       38 |      344 |       44 |     92.27% |329, 332, 338, 340-\>351, 375, 418, 427-\>429, 437, 440, 444-\>446, 447, 464, 538, 565, 567, 569, 572, 615, 636, 638, 645, 687, 691, 714, 716, 733, 735, 849, 863, 972, 999-1000, 1075, 1091, 1095, 1107, 1131, 1139, 1152, 1168, 1201-\>exit, 1203-\>exit, 1238-\>1242, 1243-\>exit, 1250, 1286-\>exit, 1289-\>exit |
| src/aiogzip/\_common.py     |      181 |        0 |      112 |        5 |     98.29% |310-\>exit, 317-\>exit, 324-\>exit, 325-\>exit, 326-\>exit |
| src/aiogzip/\_engine.py     |       30 |        3 |        6 |        3 |     83.33% |52, 72, 85 |
| src/aiogzip/\_text.py       |      674 |       38 |      306 |       30 |     92.24% |162, 292-293, 319, 349, 360, 393-395, 400, 412-414, 431-433, 472, 479, 547, 581, 635, 660, 666-\>669, 672, 712, 753-757, 759, 773, 796-797, 802-\>805, 824, 830-\>833, 904-\>907, 909, 1005-1006, 1018, 1116, 1302, 1394-\>exit, 1405-\>exit |
| **TOTAL**                   | **1631** |   **79** |  **784** |   **85** | **92.88%** |           |


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