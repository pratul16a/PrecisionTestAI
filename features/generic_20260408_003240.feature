```gherkin
@automated @generic
Feature: Search functionality
  As a user
  I want to perform searches on the website
  So that I can find relevant information

  @search @smoke
  Scenario Outline: Perform search operation
    Given I navigate to "<url>"
    When I click on "<button>"
    Then the search should be executed successfully

    Examples:
      | url                | button |
      | https://google.com | search |
```