```gherkin
@automated @generic
Feature: Application Navigation
  As a user
  I want to navigate to the application
  So that I can access the system functionality

  @smoke @navigation
  Scenario Outline: Navigate to application URL
    Given I am using the "<application>" application
    When I navigate to "<url>"
    Then I should successfully access the application

    Examples:
      | application | url                    |
      | generic     | http://localhost:3000  |
```