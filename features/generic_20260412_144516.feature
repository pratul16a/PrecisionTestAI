```gherkin
@automated @generic
Feature: Navigation Testing
  As a user
  I want to navigate to different URLs
  So that I can access the application

  @navigation @smoke
  Scenario Outline: Navigate to application URL
    Given I am on the test environment
    When I navigate to "<url>"
    Then I should be on the correct page

    Examples:
      | url                    |
      | http://localhost:3000  |
```