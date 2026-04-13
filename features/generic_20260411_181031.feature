```gherkin
@automated @generic
Feature: Navigation Functionality
  As a user of the PrecisionTest-GENERIC application
  I want to navigate to different URLs
  So that I can access the application's pages

  @navigation @smoke
  Scenario Outline: Navigate to application URL
    Given I am using the generic application
    When I navigate to "<url>"
    Then I should successfully reach the target page

    Examples:
      | url                   |
      | http://localhost:3000 |
```