```gherkin
@automated @generic
Feature: Google Search Functionality
  As a user
  I want to perform searches on Google
  So that I can find relevant information

  @smoke @search
  Scenario Outline: Perform basic search operations
    Given I navigate to "<url>"
    When I click on "<element>"
    Then the search should be executed successfully

    Examples:
      | url                | element |
      | https://google.com | search  |
```