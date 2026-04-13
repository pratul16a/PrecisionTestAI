```gherkin
@automated @generic
Feature: Browser Navigation
  As a test automation engineer
  I want to navigate to web applications and manage browser sessions
  So that I can perform automated testing of web interfaces

  @smoke @navigation
  Scenario Outline: Navigate to application and close browser
    Given I navigate to "<url>"
    And I close the browser

    Examples:
      | url                   |
      | http://localhost:3000 |
```