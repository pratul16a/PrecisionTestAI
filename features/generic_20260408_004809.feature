```gherkin
@automated @generic
Feature: Google Search Functionality
  As a user
  I want to perform searches on Google
  So that I can find relevant information

  @search @positive
  Scenario Outline: Perform search operation on Google
    Given I navigate to "<url>"
    When I click on "<search_field>"
    And I enter "<search_term>" in "<input_field>"
    Then I click on "<search_button>"

    Examples:
      | url               | search_field | search_term | input_field | search_button |
      | https://google.com| search       |             | search      | Google Search |
```