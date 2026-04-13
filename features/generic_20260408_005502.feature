```gherkin
@automated @generic
Feature: Google Search Functionality
  As a user
  I want to perform searches on Google
  So that I can find relevant information

  @smoke @search
  Scenario Outline: Perform search with different search terms
    Given I navigate to "<url>"
    When I enter "<search_term>" in "<search_field>"
    When I click on "<search_button>"
    And I close the browser

    Examples:
      | url               | search_term | search_field | search_button |
      | https://google.com|             | search       | search        |
```