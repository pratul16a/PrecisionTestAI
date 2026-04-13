```gherkin
@automated @generic
Feature: Website Navigation
  As a user
  I want to navigate to different websites
  So that I can access web content

  @smoke @navigation
  Scenario Outline: Navigate to website URL
    Given I am using a web browser
    When I navigate to "<url>"
    Then I should successfully reach the website

    Examples:
      | url                   |
      | https://example.com   |
```