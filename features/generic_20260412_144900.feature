```gherkin
@automated @generic
Feature: Web Application Navigation
  As a user
  I want to navigate to the web application
  So that I can access the application functionality

  @navigation @smoke
  Scenario Outline: Navigate to application URL
    Given I am using a web browser
    When I navigate to "<url>"
    Then I should successfully reach the application

    Examples:
      | url                     |
      | http://localhost:3000/  |
```