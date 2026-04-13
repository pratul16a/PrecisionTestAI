```gherkin
@automated @generic
Feature: Search Functionality
  As a user
  I want to perform searches on the application
  So that I can find relevant information

  @search @smoke
  Scenario Outline: Perform search operation
    Given I navigate to "<url>"
    When I click on "<search_element>"
    Then the search should be executed successfully

    Examples:
      | url                | search_element |
      | https://google.com | search         |
```