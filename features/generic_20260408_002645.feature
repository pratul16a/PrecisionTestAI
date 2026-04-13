```gherkin
@automated @generic
Feature: Website Navigation and Visibility Verification
  As a user
  I want to navigate to websites and verify element visibility
  So that I can ensure the application displays content correctly

  @navigation @visibility
  Scenario Outline: Verify element visibility on website navigation
    Given I navigate to "<url>"
    Then I should see "<element>" visible

    Examples:
      | url                    | element |
      | https://example.com    |         |
```