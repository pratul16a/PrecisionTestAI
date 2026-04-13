```gherkin
@automated @generic
Feature: Search Functionality
  As a user
  I want to perform search operations
  So that I can find relevant information

  @smoke @search
  Scenario Outline: Perform search operation
    Given I navigate to "<url>"
    When I click on "<button>"
    Then the search should be executed successfully

    Examples:
      | url                | button |
      | https://google.com | search |
```