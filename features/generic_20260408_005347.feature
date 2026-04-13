```gherkin
@automated @generic
Feature: Basic Navigation and Browser Management
  As a test automation engineer
  I want to verify basic browser navigation functionality
  So that I can ensure the application loads correctly

  @smoke @navigation
  Scenario Outline: Navigate to application and verify page load
    Given I navigate to "<url>"
    Then I should see "<expected_content>"
    And I close the browser

    Examples:
      | url                    | expected_content |
      | https://example.com    |                  |
```