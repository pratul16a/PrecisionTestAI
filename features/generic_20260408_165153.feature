```gherkin
@automated @generic
Feature: Reports Navigation
  As a user of the PrecisionTest application
  I want to navigate to the Reports section
  So that I can view and manage reports

  @smoke @navigation
  Scenario Outline: Navigate to Reports section
    Given I navigate to "<url>"
    When I click on "<navigation_item>"
    Then I should successfully access the Reports section

    Examples:
      | url                   | navigation_item |
      | http://localhost:3000 | Reports         |
```