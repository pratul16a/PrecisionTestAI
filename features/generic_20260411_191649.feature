```gherkin
@automated @generic
Feature: Website Navigation
  As a user
  I want to navigate to websites
  So that I can access web applications

  @navigation @smoke
  Scenario Outline: Navigate to website
    Given I am on a web browser
    When I navigate to "<url>"
    Then I should successfully reach the website

    Examples:
      | url                   |
      | https://example.com   |
```