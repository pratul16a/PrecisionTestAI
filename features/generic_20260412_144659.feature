```gherkin
@automated @generic
Feature: Web Navigation
  As a user
  I want to navigate to web applications
  So that I can access different websites

  @navigation @smoke
  Scenario Outline: Navigate to website
    Given I am using a web browser
    When I navigate to "<url>"
    Then I should successfully reach the website

    Examples:
      | url                 |
      | https://google.com  |
```