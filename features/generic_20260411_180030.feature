```gherkin
@automated @generic
Feature: Browser Navigation
  As a test automation engineer
  I want to navigate to different URLs
  So that I can verify browser navigation functionality

  @smoke @navigation
  Scenario Outline: Navigate to URL
    Given the browser is launched
    When I navigate to "<url>"
    Then the navigation should be successful

    Examples:
      | url        |
      | about:blank|
```