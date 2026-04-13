```gherkin
@automated @generic
Feature: Search Functionality
  As a user
  I want to perform search operations
  So that I can find relevant information

  @smoke
  Scenario Outline: Perform search with different inputs
    Given I navigate to "<url>"
    When I enter "<search_term>" in "<search_field>"
    When I click on "<search_button>"
    And I close the browser

    Examples:
      | url                 | search_term | search_field | search_button |
      | https://google.com  |             | search       | search        |
```