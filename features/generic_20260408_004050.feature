```gherkin
@automated @generic
Feature: Google Search Functionality
  As a user
  I want to perform searches on Google
  So that I can find relevant information

  @search @smoke
  Scenario Outline: Perform search on Google homepage
    Given I navigate to "<url>"
    When I click on "<element>"
    Then I should see search results

    Examples:
      | url                | element |
      | https://google.com | search  |
```